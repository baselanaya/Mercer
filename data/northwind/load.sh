#!/usr/bin/env bash
# data/northwind/load.sh
# Loads the Northwind schema and data into the database at $DATABASE_URL.
#
# Usage:
#   export DATABASE_URL=postgresql://mercer:mercer@localhost:5432/mercer_dev
#   bash data/northwind/load.sh
#
# Or pass the URL as the first argument:
#   bash data/northwind/load.sh postgresql://user:pass@localhost:5432/mydb

set -euo pipefail

DB_URL="${1:-${DATABASE_URL:-}}"

if [[ -z "$DB_URL" ]]; then
  echo "ERROR: Set DATABASE_URL or pass the connection string as the first argument." >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "→ Loading Northwind into $DB_URL ..."
psql "$DB_URL" -f "$SCRIPT_DIR/northwind.sql"
echo "✓ Northwind loaded successfully."
