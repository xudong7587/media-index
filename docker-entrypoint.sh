#!/bin/sh
set -eu

runtime_uid="${PUID:-10001}"
runtime_gid="${PGID:-10001}"

case "$runtime_uid" in
  ''|*[!0-9]*|0) echo "PUID must be a positive integer" >&2; exit 64 ;;
esac
case "$runtime_gid" in
  ''|*[!0-9]*|0) echo "PGID must be a positive integer" >&2; exit 64 ;;
esac

if [ "$(id -u)" = "0" ]; then
  mkdir -p /app/data
  chown -R "$runtime_uid:$runtime_gid" /app/data
  exec setpriv --reuid="$runtime_uid" --regid="$runtime_gid" --clear-groups "$@"
fi

exec "$@"
