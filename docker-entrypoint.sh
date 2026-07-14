#!/bin/sh
set -eu

if [ "$(id -u)" = "0" ]; then
  mkdir -p /app/data
  chown -R mediaindex:mediaindex /app/data
  exec setpriv --reuid=10001 --regid=10001 --init-groups "$@"
fi

exec "$@"
