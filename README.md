# rabbit-tunnel

Publish your local server to public via rabbit-tunnel.


```sh
pip install rabbit-tunnel

rt -n hello -p 8080 -sh rtunnel.io
# Now you can access 127.0.0.1:8080 via http(s)://hello.rtunnel.io
```

```sh
usage: rt [-h] -n NAME -p PORT [-lh LOCAL_HOST] -sh SERVER_HOST [-sp SERVER_PORT] [--server-no-tls]

Publish your local server to public via rabbit-tunnel

optional arguments:
  -h, --help            show this help message and exit
  -n NAME, --name NAME  name to register (append prefix ! to force)
  -p PORT, --port PORT  local port to connect
  -lh LOCAL_HOST, --local-host LOCAL_HOST
                        local host to connect (default: 127.0.0.1)
  -sh SERVER_HOST, --server-host SERVER_HOST
                        rabbit-tunnel-server host
  -sp SERVER_PORT, --server-port SERVER_PORT
                        rabbit-tunnel-server port (default: 443)
  --server-no-tls       disable TLS connection to rabbit-tunnel-server
```


### Requirements
- Python 3.7 - 3.9
