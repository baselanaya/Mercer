# DVDRental Test Database

Standard PostgreSQL sample database with 15 tables, ~16k rows. Used as the primary clean-schema benchmark for Mercer.

## Schema

| Table | Rows (approx) | Description |
|---|---|---|
| film | 1,000 | Film catalog |
| actor | 200 | Actors |
| film_actor | 5,462 | Film↔actor join |
| customer | 599 | Customers |
| rental | 16,044 | Rental transactions |
| payment | 14,596 | Payments |
| inventory | 4,581 | Physical disc copies |
| store | 2 | Store locations |
| staff | 2 | Employees |
| address | 603 | Addresses |
| city | 600 | Cities |
| country | 109 | Countries |
| language | 6 | Languages |
| category | 16 | Film categories |
| film_category | 1,000 | Film↔category join |

## Load

### Prerequisites

- PostgreSQL client tools (`psql`, `pg_restore`)
- `curl` or `wget`

### Steps

```bash
# Start the database (if using Docker)
docker compose -f docker/docker-compose.yml up -d postgres

# Load DVDRental
export DATABASE_URL=postgresql://mercer:mercer@localhost:5432/mercer_dev
bash data/dvdrental/load.sh
```

Or with a custom URL:

```bash
bash data/dvdrental/load.sh postgresql://user:password@host:5432/dbname
```

### What the script does

1. Downloads `dvdrental.zip` from postgresqltutorial.com (~1 MB)
2. Extracts `dvdrental.tar`
3. Runs `pg_restore` to load all tables and data

The zip file is kept in `data/dvdrental/` after the first download so subsequent runs skip the download step.

## Baseline Queries

See `data/test_queries/dvdrental_baseline.yaml` for 5 hand-written NL→SQL pairs used as Phase 0 validation targets.
