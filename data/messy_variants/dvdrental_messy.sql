-- =============================================================================
-- dvdrental_messy.sql — Chaos Inventory
-- =============================================================================
--
-- This file simulates a real-world legacy schema built by multiple teams
-- over several years with no style guide and no DBA oversight.
--
-- CHAOS INJECTED (intentional — for testing Mercer's schema linking):
--
-- 1. COLUMN ABBREVIATIONS
--    Every table has at least one cryptic abbreviation:
--      customer_id → cust_id     first_name → f_nm      last_name → l_nm
--      email       → e_addr      rental_date → rnt_dt    amount    → amt
--      film_id     → f_id        address_id  → addr_id   store_id  → st_id
--      return_date → ret_dt      payment_id  → pmt_id    inventory_id → inv_id
--
-- 2. REMOVED FOREIGN KEYS
--    All REFERENCES constraints stripped. Column values exist but are
--    undeclared — no FK graph can be built from information_schema alone.
--    (Mercer must infer join paths from semantic mappings and heuristics.)
--
-- 3. INCONSISTENT NAMING CONVENTIONS
--    cust_mstr       — snake_case (legacy)
--    f_catalog       — abbreviated snake_case
--    RentalTxn       — camelCase (added by the web team in 2018)
--    PAYMENT_LEDGER  — ALL_CAPS (imported from the finance system)
--    inv             — ultra-abbreviated
--    staff_member    — slightly different from original 'staff'
--
-- 4. DENORMALIZED TABLES
--    cust_activity:   customer + rental + payment flattened into one wide table
--                     (used by the reporting team to avoid joins)
--    FilmCatalogFull: film + category + language combined
--                     (built for the recommendation engine, never cleaned up)
--
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------
-- cust_mstr  (was: customer)
-- Naming: snake_case | Abbreviations: heavy | FKs: none
-- -----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS cust_mstr (
    cust_id     INTEGER     NOT NULL PRIMARY KEY,
    st_id       INTEGER,                            -- was store_id (no FK)
    f_nm        VARCHAR(45) NOT NULL,               -- was first_name
    l_nm        VARCHAR(45) NOT NULL,               -- was last_name
    e_addr      VARCHAR(50),                        -- was email
    addr_id     INTEGER,                            -- was address_id (no FK)
    act_bool    BOOLEAN     NOT NULL DEFAULT TRUE,  -- was activebool
    crt_dt      DATE        NOT NULL DEFAULT CURRENT_DATE, -- was create_date
    lst_upd     TIMESTAMP   DEFAULT CURRENT_TIMESTAMP,
    act         INTEGER     DEFAULT 1               -- was active (legacy int flag)
);

-- -----------------------------------------------------------------------
-- f_catalog  (was: film)
-- Naming: abbreviated snake_case | FKs: none
-- -----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS f_catalog (
    f_id        INTEGER       NOT NULL PRIMARY KEY,
    ttl         VARCHAR(255)  NOT NULL,             -- was title
    descr       TEXT,                               -- was description
    rel_yr      SMALLINT,                           -- was release_year
    lang_id     INTEGER,                            -- was language_id (no FK)
    rnt_dur     SMALLINT      NOT NULL DEFAULT 3,   -- was rental_duration
    rnt_rt      NUMERIC(4,2)  NOT NULL DEFAULT 4.99, -- was rental_rate
    lng         SMALLINT,                           -- was length
    repl_cst    NUMERIC(5,2)  NOT NULL DEFAULT 19.99, -- was replacement_cost
    rtg         VARCHAR(10),                        -- was rating (G/PG/PG-13/R/NC-17)
    spc_ftrs    TEXT[],                             -- was special_features
    lst_upd     TIMESTAMP     DEFAULT CURRENT_TIMESTAMP
);

-- -----------------------------------------------------------------------
-- RentalTxn  (was: rental)
-- Naming: camelCase — added by the web team | FKs: none
-- -----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS "RentalTxn" (
    rentalId    INTEGER     NOT NULL PRIMARY KEY,
    rnt_dt      TIMESTAMP   NOT NULL,               -- was rental_date
    invId       INTEGER,                            -- was inventory_id (no FK)
    custId      INTEGER,                            -- was customer_id (no FK)
    retDt       TIMESTAMP,                          -- was return_date
    staffId     INTEGER,                            -- was staff_id (no FK)
    lastUpd     TIMESTAMP   DEFAULT CURRENT_TIMESTAMP
);

-- -----------------------------------------------------------------------
-- PAYMENT_LEDGER  (was: payment)
-- Naming: ALL_CAPS — imported from finance system | FKs: none
-- -----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS "PAYMENT_LEDGER" (
    PMT_ID      INTEGER       NOT NULL PRIMARY KEY,
    CUST_ID     INTEGER,                            -- was customer_id (no FK)
    STAFF_ID    INTEGER,                            -- was staff_id (no FK)
    RNT_ID      INTEGER,                            -- was rental_id (no FK)
    AMT         NUMERIC(5,2)  NOT NULL,             -- was amount
    PMT_DT      TIMESTAMP     NOT NULL              -- was payment_date
);

-- -----------------------------------------------------------------------
-- inv  (was: inventory)
-- Naming: ultra-abbreviated | FKs: none
-- -----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS inv (
    inv_id      INTEGER NOT NULL PRIMARY KEY,       -- was inventory_id
    f_id        INTEGER,                            -- was film_id (no FK)
    st_id       INTEGER,                            -- was store_id (no FK)
    lst_upd     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- -----------------------------------------------------------------------
-- staff_member  (was: staff)
-- Naming: slightly renamed | FKs: none
-- -----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS staff_member (
    staff_id    INTEGER       NOT NULL PRIMARY KEY,
    f_nm        VARCHAR(45)   NOT NULL,             -- was first_name
    l_nm        VARCHAR(45)   NOT NULL,             -- was last_name
    addr_id     INTEGER,                            -- was address_id (no FK)
    e_addr      VARCHAR(50),                        -- was email
    st_id       INTEGER,                            -- was store_id (no FK)
    active      BOOLEAN       NOT NULL DEFAULT TRUE,
    uname       VARCHAR(16)   NOT NULL,             -- was username
    lst_upd     TIMESTAMP     DEFAULT CURRENT_TIMESTAMP
);

-- -----------------------------------------------------------------------
-- store_loc  (was: store)
-- Naming: snake_case with slight rename | FKs: none
-- -----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS store_loc (
    st_id       INTEGER   NOT NULL PRIMARY KEY,     -- was store_id
    mgr_stf_id  INTEGER,                            -- was manager_staff_id (no FK)
    addr_id     INTEGER,                            -- was address_id (no FK)
    lst_upd     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- -----------------------------------------------------------------------
-- actor  (kept original name — inconsistency is the point)
-- -----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS actor (
    actor_id    INTEGER     NOT NULL PRIMARY KEY,
    first_name  VARCHAR(45) NOT NULL,
    last_name   VARCHAR(45) NOT NULL,
    last_update TIMESTAMP   DEFAULT CURRENT_TIMESTAMP
);

-- -----------------------------------------------------------------------
-- film_actor  (kept original join table naming)
-- FKs: none — but values correspond to f_catalog.f_id and actor.actor_id
-- -----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS film_actor (
    actor_id    INTEGER NOT NULL,                   -- no FK to actor
    f_id        INTEGER NOT NULL,                   -- no FK to f_catalog (NOTE: renamed col)
    last_update TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (actor_id, f_id)
);

-- -----------------------------------------------------------------------
-- cat  (was: category)
-- Naming: abbreviated | FKs: none
-- -----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS cat (
    cat_id      INTEGER     NOT NULL PRIMARY KEY,   -- was category_id
    cat_nm      VARCHAR(25) NOT NULL,               -- was name
    last_update TIMESTAMP   DEFAULT CURRENT_TIMESTAMP
);

-- -----------------------------------------------------------------------
-- film_cat  (was: film_category)
-- Naming: abbreviated | FKs: none
-- -----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS film_cat (
    f_id        INTEGER NOT NULL,                   -- was film_id (no FK)
    cat_id      INTEGER NOT NULL,                   -- was category_id (no FK)
    last_update TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (f_id, cat_id)
);

-- =======================================================================
-- DENORMALIZED TABLE 1: cust_activity
--
-- Created by the reporting team in 2017 to "make dashboards faster".
-- Combines cust_mstr + RentalTxn + PAYMENT_LEDGER into one wide table.
-- Updated nightly by a cron job (source of truth is the transactional tables).
-- Frequently out of sync by up to 24 hours.
-- =======================================================================
CREATE TABLE IF NOT EXISTS cust_activity (
    -- Customer fields (from cust_mstr)
    cust_id     INTEGER,
    f_nm        VARCHAR(45),
    l_nm        VARCHAR(45),
    e_addr      VARCHAR(50),
    act_bool    BOOLEAN,
    -- Rental fields (from RentalTxn)
    rental_id   INTEGER,
    rnt_dt      TIMESTAMP,
    ret_dt      TIMESTAMP,
    inv_id      INTEGER,
    -- Payment fields (from PAYMENT_LEDGER)
    pmt_id      INTEGER,
    amt         NUMERIC(5,2),
    pmt_dt      TIMESTAMP,
    -- Derived / redundant
    is_returned BOOLEAN GENERATED ALWAYS AS (ret_dt IS NOT NULL) STORED,
    snapshot_ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Index to support common dashboard query patterns
CREATE INDEX IF NOT EXISTS idx_cust_activity_cust ON cust_activity (cust_id);
CREATE INDEX IF NOT EXISTS idx_cust_activity_rnt  ON cust_activity (rnt_dt);

-- =======================================================================
-- DENORMALIZED TABLE 2: FilmCatalogFull
--
-- Built in 2020 for the recommendation engine microservice.
-- Combines f_catalog + cat + language into a single flat table.
-- camelCase because the ML team wrote it and never read the style guide.
-- language name is stored as a raw string (no FK to a language table).
-- =======================================================================
CREATE TABLE IF NOT EXISTS "FilmCatalogFull" (
    -- Film fields (from f_catalog)
    "filmId"        INTEGER       NOT NULL PRIMARY KEY,  -- was f_id
    "filmTitle"     VARCHAR(255)  NOT NULL,
    "releaseYear"   SMALLINT,
    "rentalRate"    NUMERIC(4,2),
    "rentalDur"     SMALLINT,
    "rating"        VARCHAR(10),
    "filmDescr"     TEXT,
    -- Category (denormalized from cat)
    "catId"         INTEGER,
    "catName"       VARCHAR(25),
    -- Language (denormalized — stored as string, no FK)
    "langName"      VARCHAR(20),
    -- Metadata
    "lastRefreshed" TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

COMMIT;
