#!/bin/bash
echo "entrypoint.sh"
gunicorn -w 4 'wsgiproxy:app' -b "127.0.0.1:8443" --keyfile /etc/ray/tls/tls.key  --certfile /etc/ray/tls/tls.crt  --ca-certs /etc/ca/tls/ca.crt  --access-logfile=-
