#!/bin/sh
set -eu

runtime_uid="${PUID:-10001}"
runtime_gid="${PGID:-10001}"
strm_output_root="${STRM_OUTPUT_ROOT:-/strm}"

case "$runtime_uid" in
  ''|*[!0-9]*|0) echo "PUID must be a positive integer" >&2; exit 64 ;;
esac
case "$runtime_gid" in
  ''|*[!0-9]*|0) echo "PGID must be a positive integer" >&2; exit 64 ;;
esac

if [ "$(id -u)" = "0" ]; then
  mkdir -p /app/data
  chown -R "$runtime_uid:$runtime_gid" /app/data

  if [ -d "$strm_output_root" ]; then
    if ! chown "$runtime_uid:$runtime_gid" "$strm_output_root"; then
      echo "Unable to assign STRM output directory $strm_output_root to PUID=$runtime_uid PGID=$runtime_gid" >&2
      exit 73
    fi
    chmod u+rwx "$strm_output_root"
  fi

  exec setpriv --reuid="$runtime_uid" --regid="$runtime_gid" --clear-groups "$@"
fi

exec "$@"
