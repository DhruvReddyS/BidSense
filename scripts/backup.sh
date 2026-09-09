#!/usr/bin/env bash
set -euo pipefail
destination="${1:?usage: scripts/backup.sh /absolute/backup/directory}"
mkdir -p "$destination"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
docker compose exec -T postgres pg_dump -U "${POSTGRES_USER:-tenderiq}" "${POSTGRES_DB:-tenderiq}" | gzip > "$destination/postgres-$stamp.sql.gz"
docker run --rm -v tender_system_qdrantdata:/source:ro -v "$destination:/backup" alpine tar -czf "/backup/qdrant-$stamp.tar.gz" -C /source .
echo "Backups written to $destination"
