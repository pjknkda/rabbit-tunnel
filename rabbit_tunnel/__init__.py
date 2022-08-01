from __future__ import annotations

import asyncio
import logging
import os
import random
import re
import time
from typing import TYPE_CHECKING, Any, NamedTuple

import msgpack
from websockets.exceptions import (
    ConnectionClosedError as WsConnectionClosedError,
)
from websockets.exceptions import ConnectionClosedOK as WsConnectionClosedOK
from websockets.exceptions import InvalidStatusCode
from websockets.legacy.client import connect as ws_connect

if TYPE_CHECKING:
    from websockets.legacy.client import WebSocketClientProtocol

logger = logging.getLogger(__name__)

_READ_BUFFER = 4 * 2**10  # 4KB
_PORXY_CONNECTION_KEEPALIVE_INTERVAL = 30  # 30 seconds


class _DoReconnect(Exception):
    pass


class ConnInfo(NamedTuple):
    puller_task: asyncio.Task
    f2b_queue: asyncio.Queue[dict[str, Any]]


async def _puller(
    conn_uid_to_conn_info: dict[str, ConnInfo],
    host: str,
    port: int,
    conn_uid: str,
    ws: WebSocketClientProtocol,
) -> None:
    conn_info = conn_uid_to_conn_info[conn_uid]

    is_closed = False

    async def _close(reason: str) -> None:
        nonlocal is_closed
        if is_closed:
            return

        try:
            await ws.send(
                msgpack.dumps(
                    {
                        "type": "closed",
                        "conn_uid": conn_uid,
                        "reason": reason,
                    }
                )
            )
        except WsConnectionClosedError:
            pass
        except Exception:
            logger.warning(
                "Failed to send close message for conn %s",
                conn_uid,
                exc_info=True,
            )

    reader: asyncio.StreamReader | None = None
    writer: asyncio.StreamWriter | None = None

    async def _keepalive_handler() -> None:
        try:
            while True:
                await asyncio.sleep(_PORXY_CONNECTION_KEEPALIVE_INTERVAL)
                await ws.send(
                    msgpack.dumps(
                        {
                            "type": "keepalive",
                            "conn_uid": conn_uid,
                        }
                    )
                )

        finally:
            await _close("server-keepalive-timeout")
            conn_info.f2b_queue.put_nowait(
                {
                    "type": "closed",
                    "reason": "server-keepalive-timeout",
                }
            )

    keepalive_handler_task = asyncio.create_task(_keepalive_handler())

    async def _reader_puller() -> None:
        try:
            if reader is None:
                raise RuntimeError("Reader is not initialized")

            while True:
                try:
                    data = await reader.read(_READ_BUFFER)
                except (RuntimeError, ConnectionError):
                    break

                if not data:
                    break

                try:
                    await ws.send(
                        msgpack.dumps(
                            {
                                "type": "data",
                                "conn_uid": conn_uid,
                                "data": data,
                            }
                        )
                    )
                except WsConnectionClosedError:
                    break
        finally:
            await _close("local-connection-closed")
            conn_info.f2b_queue.put_nowait(
                {
                    "type": "closed",
                    "reason": "local-connection-closed",
                }
            )

    reader_puller_task: asyncio.Task | None = None

    try:
        while True:
            msg = await conn_info.f2b_queue.get()

            if msg["type"] == "setup":
                if not (
                    reader is None
                    and writer is None
                    and reader_puller_task is None
                ):
                    raise RuntimeError(
                        "Invalid state: duplicated setup messages"
                    )

                try:
                    reader, writer = await asyncio.open_connection(host, port)
                except OSError:
                    await _close("local-connection-open-failed")
                    break

                await ws.send(
                    msgpack.dumps(
                        {
                            "type": "setup-ok",
                            "conn_uid": conn_uid,
                        }
                    )
                )

                reader_puller_task = asyncio.create_task(_reader_puller())

            elif msg["type"] == "data":
                if not (reader is not None and writer is not None):
                    raise RuntimeError(
                        "Invalid state: data message before setup message"
                    )

                try:
                    writer.write(msg["data"])
                    await writer.drain()
                except (RuntimeError, ConnectionResetError, BrokenPipeError):
                    await _close("local-connection-closed")
                    break

            elif msg["type"] == "closed":
                logger.debug(
                    "Connection %s is gracefully closed : %s",
                    conn_uid,
                    msg["reason"],
                )
                break

            else:
                logger.warning("Unexpected msg type: %s", msg["type"])

            conn_info.f2b_queue.task_done()

    except WsConnectionClosedError:
        logger.debug(
            "WS connection is closed : cleanup connection %s", conn_uid
        )

    except Exception:
        logger.exception("Exception from tunnel proxy connection %s", conn_uid)
        await _close("client-error")

    finally:
        await _close("cleanup")

        if reader_puller_task is not None:
            try:
                reader_puller_task.cancel()
                await reader_puller_task
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.exception(
                    "Exception from tunnel proxy connection reader puller"
                )

        try:
            keepalive_handler_task.cancel()
            await keepalive_handler_task
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception(
                "Exception from tunnel proxy connection keepalive sender"
            )

        if writer is not None:
            try:
                writer.close()
                await writer.wait_closed()
            except (RuntimeError, ConnectionError):
                pass

        del conn_uid_to_conn_info[conn_uid]


async def _run(
    name: str,
    port: int,
    local_host: str,
    server_host: str,
    server_port: int,
    server_no_tls: bool,
    secret_token: str,
) -> None:
    if re.match(r"^([^\.\/\s]+)$", name) is None:
        raise ValueError("Invalid subdomain name", port)

    if port < 1:
        raise ValueError("Invalid local port", port)

    _conn_uid_to_conn_info: dict[str, ConnInfo] = {}

    try:
        server_endpoint = f"ws{'' if server_no_tls else 's'}://{server_host}:{server_port}/tunnel/{name}"

        if not secret_token:
            secret_token = os.getenv("SECRET_TOKEN", "")

        if secret_token:
            server_endpoint = f"{server_endpoint}?token={secret_token}"

        async with ws_connect(uri=server_endpoint) as ws:
            welcome_received = False
            while True:
                msg_raw = await ws.recv()

                try:
                    msg = msgpack.loads(msg_raw)
                    if not (
                        isinstance(msg, dict)
                        and "type" in msg
                        and "conn_uid" in msg
                    ):
                        raise RuntimeError("Unexpected msg structure")
                except Exception:
                    continue

                if msg["type"] == "welcome":
                    if welcome_received:
                        raise RuntimeError(
                            "Protocol violation: duplicated welcome messages"
                        )
                    welcome_received = True
                    print(f'Host : {name}.{msg["domain"]}')
                    continue

                if not welcome_received:
                    raise RuntimeError(
                        "Protocol violation: welcome message is expected"
                    )

                if msg["type"] == "setup":
                    if msg["conn_uid"] in _conn_uid_to_conn_info:
                        logger.warning(
                            "Invalid state: connection is already registered"
                        )
                        continue

                    _conn_uid_to_conn_info[msg["conn_uid"]] = ConnInfo(
                        puller_task=asyncio.create_task(
                            _puller(
                                _conn_uid_to_conn_info,
                                local_host,
                                port,
                                msg["conn_uid"],
                                ws,
                            )
                        ),
                        f2b_queue=asyncio.Queue(),
                    )

                conn_info = _conn_uid_to_conn_info.get(msg["conn_uid"])

                if conn_info is None:
                    continue

                await conn_info.f2b_queue.put(msg)

    except WsConnectionClosedError as err:
        if err.code == 1006:
            logger.error("Server connection is lost")
            raise _DoReconnect()
        elif err.code == 4900:
            logger.error("Name is already in use")
        elif err.code == 4901:
            logger.error("Name is evicted")
        elif err.code == 4902:
            logger.error("Server is closed")
            raise _DoReconnect()
        else:
            logger.error("Unexpected WS disconnection")
            raise _DoReconnect()

    except (asyncio.CancelledError, WsConnectionClosedOK):
        pass

    except InvalidStatusCode as err:
        if err.status_code == 403:
            logger.error("Possibility wrong secret token")
            return
        raise _DoReconnect()

    except Exception:
        logger.exception("Unexpected exception")
        raise _DoReconnect()


async def run(
    name: str,
    port: int,
    local_host: str,
    server_host: str,
    server_port: int,
    server_no_tls: bool,
    secret_token: str,
    auto_reconnect: bool,
) -> None:
    failure_cnt, failure_ts = 0, time.monotonic()
    while True:
        try:
            await _run(
                name,
                port,
                local_host,
                server_host,
                server_port,
                server_no_tls,
                secret_token,
            )
        except _DoReconnect:
            if time.monotonic() - failure_ts > 60:
                failure_cnt = 0

            if auto_reconnect:
                failure_cnt += 1
                failure_ts = time.monotonic()

                delay = min(random.random() * 5 + 2**failure_cnt, 30)
                logger.warning("Do reconnect... (delay: %.2lfs)", delay)

                await asyncio.sleep(delay)
                continue

        return
