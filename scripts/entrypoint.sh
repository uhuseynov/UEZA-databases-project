#!/usr/bin/env bash

set -euo pipefail

echo "Waiting for MariaDB..."

python - <<'PY'
import socket
import time
import os

host = os.environ.get("MARIADB_HOST", "db")
port = int(os.environ.get("MARIADB_PORT", "3306"))

for attempt in range(60):
    try:
        with socket.create_connection((host, port), timeout=2):
            print("MariaDB is reachable.")
            break
    except OSError:
        time.sleep(1)
else:
    raise SystemExit("MariaDB did not become reachable in time.")
PY

# The schema is not managed here: schema.sql creates it when the database volume is first
# created (docs/database/Schema.md).

# Run the application as the unprivileged user "ueza", not as root. The container starts as
# root only to repair the ownership of the cache directories: a volume created by an earlier
# version of this image (which ran as root) holds root-owned files that "ueza" could not
# write. Nothing is changed when everything already belongs to "ueza", and the check only
# looks, so a large model cache is not walked twice. If the container was started as another
# user already (docker run --user, Compose `user:`), the command runs as that user as is.
if [ "$(id -u)" = "0" ]; then
    for dir in /app/.cache "${CACHE_DIR:-}" "${HF_HOME:-}"; do
        if [ -n "$dir" ] && [ -d "$dir" ] && [ -n "$(find "$dir" -not -user ueza -print -quit)" ]; then
            echo "Giving the user ueza ownership of $dir (created by an earlier root container)..."
            chown -R ueza:ueza "$dir"
        fi
    done

    echo "Starting application as user ueza..."
    exec setpriv --reuid=ueza --regid=ueza --init-groups "$@"
fi

echo "Starting application as uid $(id -u)..."

exec "$@"
