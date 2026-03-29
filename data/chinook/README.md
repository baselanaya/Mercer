# Chinook Test Database

A cross-platform sample database modelling a digital media store (artists, albums, tracks, invoices, customers). Available in SQLite, PostgreSQL, and MySQL flavours.

## Schema (11 tables)

| Table | Description |
|---|---|
| Artist | Music artists |
| Album | Albums (belong to Artist) |
| Track | Individual tracks (belong to Album, Genre, MediaType) |
| Genre | Genre lookup |
| MediaType | File format lookup (MP3, AAC, etc.) |
| Playlist | User playlists |
| PlaylistTrack | Playlist↔Track join |
| Customer | Customers worldwide |
| Employee | Support staff |
| Invoice | Purchase invoices (belong to Customer) |
| InvoiceLine | Invoice line items (belong to Invoice, Track) |

## Download

The official Chinook SQLite file is maintained on GitHub:

```bash
curl -fsSL \
  "https://github.com/lerocha/chinook-database/raw/master/ChinookDatabase/DataSources/Chinook_Sqlite.sqlite" \
  -o data/chinook/Chinook.sqlite
```

Or download the PostgreSQL version:

```bash
curl -fsSL \
  "https://github.com/lerocha/chinook-database/raw/master/ChinookDatabase/DataSources/Chinook_PostgreSql.sql" \
  -o data/chinook/chinook_postgres.sql

# Then load:
psql "$DATABASE_URL" -f data/chinook/chinook_postgres.sql
```

## Use in Mercer

Point Mercer at the SQLite file:

```bash
export DATABASE_URL=sqlite+aiosqlite:///data/chinook/Chinook.sqlite
uvicorn app.api.main:app --reload --port 8000
```

Chinook is used as a secondary clean-schema baseline alongside DVDRental and Northwind. Its join-heavy schema (tracks → albums → artists, invoices → lines → tracks) makes it good for testing multi-hop FK path discovery.
