import argparse
import asyncio

try:
    import uvloop

    uvloop.install()
except ImportError:
    pass


def main() -> None:
    from rabbit_tunnel import run

    arg_parser = argparse.ArgumentParser(
        description="Publish your local server to public via rabbit-tunnel",
    )

    arg_parser.add_argument(
        "-n",
        "--name",
        help="name to register (append prefix ! to force)",
        required=True,
    )
    arg_parser.add_argument(
        "-p",
        "--port",
        type=int,
        help="local port to connect",
        required=True,
    )

    arg_parser.add_argument(
        "-lh",
        "--local-host",
        default="127.0.0.1",
        help="local host to connect (default: 127.0.0.1)",
    )

    arg_parser.add_argument(
        "-sh",
        "--server-host",
        help="rabbit-tunnel-server host",
        required=True,
    )
    arg_parser.add_argument(
        "-sp",
        "--server-port",
        default=443,
        help="rabbit-tunnel-server port (default: 443)",
    )
    arg_parser.add_argument(
        "--server-no-tls",
        action="store_true",
        help="disable TLS connection to rabbit-tunnel-server",
    )

    arg_parser.add_argument(
        "-st",
        "--secret-token",
        default="",
        help=(
            "token for auth to the server that is configured with secret key "
            "(env SECRET_TOKEN is also supported)"
        ),
    )

    arg_parser.add_argument(
        "--auto-reconnect",
        default=False,
        action="store_true",
        help="automatically reconnect if server-side error occurs",
    )

    args = arg_parser.parse_args()

    try:
        asyncio.run(
            run(
                args.name,
                args.port,
                args.local_host,
                args.server_host,
                args.server_port,
                args.server_no_tls,
                args.secret_token,
                args.auto_reconnect,
            )
        )
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
