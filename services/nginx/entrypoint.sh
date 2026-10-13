#!/bin/sh
# Generate a self-signed certificate so TLS works out of the box in dev/demo.
# Production replaces these certs with real ones (mounted secret/volume).
set -e

mkdir -p /etc/nginx/certs
if [ ! -f /etc/nginx/certs/server.crt ]; then
  openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
    -keyout /etc/nginx/certs/server.key \
    -out /etc/nginx/certs/server.crt \
    -subj "/CN=localhost" >/dev/null 2>&1
fi

exec "$@"