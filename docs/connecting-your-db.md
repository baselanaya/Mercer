# Connecting Your Database to Mercer

This guide walks through pointing Mercer at a real PostgreSQL database, ingesting its schema, and verifying that schema linking is working correctly.

---

## 1. Install Mercer

```bash
git clone https://github.com/baselanaya/mercer.git
cd mercer
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` and set at minimum:

```bash
DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/your_db
ANTHROPIC_API_KEY=sk-ant-...    # or OPENAI_API_KEY for OpenAI fallback
```

Optional but recommended for production:

```bash
REDIS_URL=redis://localhost:6379/0  # for schema caching
SGLANG_URL=http://localhost:30000   # if running a local model
```

---

## 2. Point at Your PostgreSQL Database

Mercer uses SQLAlchemy async connection strings. The format is:

| Database | Connection string |
|---|---|
| PostgreSQL | `postgresql+asyncpg://user:pass@host:5432/dbname` |
| MySQL | `mysql+aiomysql://user:pass@host:3306/dbname` |
| SQLite | `sqlite+aiosqlite:///path/to/file.db` |
| DuckDB | `duckdb:///path/to/file.duckdb` |

Set `DATABASE_URL` in `.env`.

---

## 3. Run ingest_schema.py

`ingest_schema.py` connects to your database, introspects the full schema, applies your `config/mappings.yaml` annotations, and writes the result to the Redis schema cache. The pipeline reads from this cache on every query — skipping re-introspection.

```bash
python scripts/ingest_schema.py --db-url "$DATABASE_URL"
```

With a custom mappings file:

```bash
python scripts/ingest_schema.py \
  --db-url "$DATABASE_URL" \
  --mappings config/my_schema.yaml
```

Expected output:

```
Introspecting schema for: postgresql+asyncpg://...
Found 23 tables, 184 columns
Semantic annotations loaded from config/mappings.yaml
Schema written to Redis cache (hash: a3f2b1c9)
Done.
```

If Redis isn't running, the pipeline will re-introspect on every startup — still correct, just slower.

---

## 4. Write Your mappings.yaml

This is the highest-leverage configuration file. It tells Mercer what your cryptic column names actually mean.

### Minimal example — no messy schema

If your schema has clear, descriptive names (`customer_id`, `order_date`, `total_amount`), you can start with an empty mappings file and add entries only where needed:

```yaml
# config/mappings.yaml
tables: {}
glossary: {}
```

### Real messy schema walkthrough

Say you have a legacy ERP schema with these tables:

```sql
CREATE TABLE cust_mstr (
  cust_id     INTEGER PRIMARY KEY,
  cust_nm     VARCHAR(100),    -- customer name
  cust_seg_cd CHAR(4),         -- segment code: RETL, CORP, SMB
  e_add       VARCHAR(200),    -- email address (legacy, nullable)
  acct_mgr_id INTEGER          -- FK to emp_tbl.emp_id
);

CREATE TABLE ord_hdr (
  ord_id    INTEGER PRIMARY KEY,
  cust_fk   INTEGER,           -- FK to cust_mstr.cust_id (no FK constraint!)
  ord_dt    DATE,
  tot_amt   DECIMAL(12,2),
  ship_stat CHAR(2)            -- 'SH'=shipped, 'PE'=pending, 'CA'=cancelled
);
```

Your `mappings.yaml`:

```yaml
tables:
  cust_mstr:
    description: "Customer master — one row per customer account"
    columns:
      cust_id:     "Primary key — customer ID"
      cust_nm:     "Customer full name"
      cust_seg_cd: "Customer segment code: RETL=Retail, CORP=Corporate, SMB=Small Business"
      e_add:       "Customer email address (legacy field, may be NULL for old accounts)"
      acct_mgr_id: "FK to emp_tbl.emp_id — assigned account manager"

  ord_hdr:
    description: "Order header — one row per order"
    columns:
      ord_id:    "Primary key — order ID"
      cust_fk:   "FK to cust_mstr.cust_id — the ordering customer (no DB constraint)"
      ord_dt:    "Order placement date"
      tot_amt:   "Total order value in USD"
      ship_stat: "Shipping status: SH=Shipped, PE=Pending, CA=Cancelled"

glossary:
  revenue:      "SUM of ord_hdr.tot_amt for completed orders"
  churn:        "Customers with no orders in the past 90 days (no rows in ord_hdr)"
  active:       "Customers with at least one order in the past 30 days"
  segment:      "cust_mstr.cust_seg_cd — customer tier classification"
  total spend:  "SUM of ord_hdr.tot_amt grouped by cust_mstr.cust_id"
```

**Guideline for column descriptions:**
- Include the data type if it affects queries (`DECIMAL(12,2)`, `CHAR(2)`)
- Enumerate known enum values with their meaning
- Explicitly name hidden FK relationships (columns without DB constraints)
- Note nullable columns that are commonly empty
- Use business language, not technical language

**Guideline for glossary terms:**
- Map business vocabulary directly to SQL expressions
- Include the table + column in the definition so the LLM has full context
- Cover synonyms: "revenue", "sales", "total spend", "income" might all mean the same thing

---

## 5. Verify Schema Linking Is Working

After ingest, start the server:

```bash
uvicorn app.api.main:app --reload --port 8000
```

### Check the schema endpoint

```bash
curl -s -H "x-api-key: dev-key" http://localhost:8000/schema | python3 -m json.tool | head -40
```

You should see your tables with descriptions populated from `mappings.yaml`.

### Run a few test queries

Send a query that exercises your messy schema:

```bash
curl -s -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -H "x-api-key: dev-key" \
  -d '{"question": "Which corporate customers placed orders last month?"}' \
  | python3 -m json.tool
```

Check the `reasoning_trace` field in the response:

```json
{
  "reasoning_trace": {
    "entity_matches": [
      {"token": "corporate", "table": "cust_mstr", "column": "cust_seg_cd", "score": 0.91},
      {"token": "orders",    "table": "ord_hdr",   "column": null,           "score": 0.88}
    ],
    "glossary_expansions": {"corporate": "CORP segment in cust_mstr.cust_seg_cd"},
    "tables_selected": ["cust_mstr", "ord_hdr"],
    "correction_steps": 0
  }
}
```

**Good signs:**
- `entity_matches` includes relevant tables and columns with high scores (> 0.7)
- `glossary_expansions` shows your mappings are being applied
- `tables_selected` contains exactly the tables needed — not extra noise
- `correction_steps: 0` (no retries needed)

---

## 6. Troubleshooting: Wrong Tables Selected

### Symptom: unrelated tables appear in `tables_selected`

**Cause:** BM25 scoring is matching on generic tokens ("id", "date", "name") that appear in many tables.

**Fix:** Add `description` entries to the noisy tables to help the schema linker distinguish them:

```yaml
tables:
  audit_log:
    description: "Internal audit trail — do NOT use for business queries"
  sys_config:
    description: "System configuration — internal settings only"
```

The schema linker uses these descriptions when scoring table relevance.

---

### Symptom: correct table is missing from `tables_selected`

**Cause:** The table has a cryptic name with no mapping, so BM25 scores it low.

**Fix:** Add a description that includes the business vocabulary used in queries:

```yaml
tables:
  prj_alloc_tbl:
    description: "Project allocations — tracks employee hours billed to each project"
```

If the user asks "how many hours were billed to Project X", the description now creates a match.

---

### Symptom: SQL uses wrong join path (cartesian product or wrong FK)

**Cause:** FK relationship not declared in DB schema, so the graph builder can't find it.

**Fix 1:** Add a FK hint in the column description:

```yaml
ord_hdr:
  columns:
    cust_fk: "FK to cust_mstr.cust_id — join condition: ord_hdr.cust_fk = cust_mstr.cust_id"
```

**Fix 2:** Add an explicit FK entry in the mappings (Phase 5 feature, use description for now).

---

### Symptom: numeric filter is wrong (e.g. `cust_seg_cd = 'CORPORATE'` instead of `'CORP'`)

**Cause:** The LLM doesn't know the actual enum values.

**Fix:** Include the enum mapping in the column description:

```yaml
cust_seg_cd: "Customer segment code: RETL=Retail, CORP=Corporate, SMB=Small Business, ENTL=Enterprise"
```

---

### Symptom: glossary term not being expanded

**Cause:** The question phrasing doesn't match the glossary key exactly.

**Fix:** Add synonyms as separate keys pointing at the same definition:

```yaml
glossary:
  revenue:     "SUM of ord_hdr.tot_amt WHERE ship_stat = 'SH'"
  sales:       "SUM of ord_hdr.tot_amt WHERE ship_stat = 'SH'"
  income:      "SUM of ord_hdr.tot_amt WHERE ship_stat = 'SH'"
  total sales: "SUM of ord_hdr.tot_amt WHERE ship_stat = 'SH'"
```
