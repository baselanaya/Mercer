#!/usr/bin/env bash
# data/dvdrental/load.sh
# Downloads the DVDRental PostgreSQL sample database and loads it into $DATABASE_URL.
#
# Usage:
#   export DATABASE_URL=postgresql://mercer:mercer@localhost:5432/mercer_dev
#   bash data/dvdrental/load.sh
#
# Or pass the URL as the first argument:
#   bash data/dvdrental/load.sh postgresql://user:pass@localhost:5432/mydb

set -euo pipefail

DB_URL="${1:-${DATABASE_URL:-}}"

if [[ -z "$DB_URL" ]]; then
  echo "ERROR: Set DATABASE_URL or pass the connection string as the first argument." >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ZIP_URL="https://www.postgresqltutorial.com/wp-content/uploads/2019/05/dvdrental.zip"
ZIP_FILE="$SCRIPT_DIR/dvdrental.zip"
TAR_FILE="$SCRIPT_DIR/dvdrental.tar"

# ---- Download ---------------------------------------------------------------
if [[ ! -f "$TAR_FILE" ]]; then
  if [[ ! -f "$ZIP_FILE" ]]; then
    echo "→ Downloading DVDRental dump..."
    if command -v curl &>/dev/null; then
      curl -fsSL "$ZIP_URL" -o "$ZIP_FILE"
    elif command -v wget &>/dev/null; then
      wget -q "$ZIP_URL" -O "$ZIP_FILE"
    else
      echo "ERROR: Neither curl nor wget found. Install one and retry." >&2
      exit 1
    fi
  fi
  echo "→ Extracting..."
  unzip -o -q "$ZIP_FILE" -d "$SCRIPT_DIR"
fi

# ---- Load -------------------------------------------------------------------
echo "→ Restoring DVDRental into $DB_URL ..."
pg_restore --no-owner --no-acl -d "$DB_URL" "$TAR_FILE"

echo "✓ DVDRental loaded successfully."
