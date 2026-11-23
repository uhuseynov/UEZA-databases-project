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

echo "Starting application..."

exec "$@"