# BidSense demo database

`bidsense_demo_2026-11-14.dump` is a PostgreSQL 16 custom-format backup containing
the prepared vendor and company demo accounts, future-dated tenders, submissions,
and saved review decisions.

## Restore into an empty database

```bash
createdb -U tenderiq tenderiq
pg_restore -U tenderiq -d tenderiq demo_exports/bidsense_demo_2026-11-14.dump
```

For Docker Compose, start PostgreSQL first and restore through the container:

```bash
docker compose up -d postgres
docker cp demo_exports/bidsense_demo_2026-11-14.dump tenderiq-postgres:/tmp/bidsense-demo.dump
docker exec tenderiq-postgres pg_restore -U tenderiq -d tenderiq /tmp/bidsense-demo.dump
```

Restore into an empty database to avoid duplicate rows. Environment files and API
keys are intentionally not included.

## Demo logins

- Vendor: `demo-vendor@bidsense.local` / `BidSenseVendor#2026`
- Company reviewer: `demo-reviewer@bidsense.local` / `BidSenseDemo#2026`

SHA-256:

```text
11555dd03f407ce93fb1b0afb8304336571deb701fc0a89005c8974e9e18374c
```
