#!/usr/bin/env bash
set -euo pipefail
source .env
mkdir -p backups
pg_dump "$DATABASE_URL" | gzip > "backups/kareem-$(date +%Y%m%d-%H%M%S).sql.gz"
echo "Backup created."
