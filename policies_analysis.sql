/*
================================================================================
Insurance Pricing Analytics - SQL analysis (SQLite)
================================================================================

Purpose
    Inspect, clean and analyse the French motor third-party liability data
    (freMTPL2) with SQL, as a complement to the Python models in main.py,
    validation.py and features.py.

How to run
    1. python main.py           -> creates insurance.db with the raw tables
                                   policies (freMTPL2freq) and claims (freMTPL2sev)
    2. python run_sql.py        -> runs this file statement by statement and
                                   prints every result with its run time
       (alternatively run single queries in any SQLite client, e.g. DB Browser
       for SQLite or the SQLite extension in VS Code)

Structure
    CHAPTER 0  Setup: indexes and query plans
    CHAPTER 1  Data quality on the RAW data
    CHAPTER 2  Cleaning: consistent tables policies_clean / claims_clean
    CHAPTER 3  Portfolio metrics and segmentation on the CLEAN data
    CHAPTER 4  Advanced analyses (window functions)

Conventions
    - table aliases: p = policies, c = claims, cc = claim counts per policy
    - rating bands are identical to the Python code (data_prep.py):
      age 18-25 / 26-40 / 41-60 / 61+,
      Bonus-Malus <=50 / 51-64 / 65-80 / 81-100 / 101-125 / >125
    - results quoted in comments were produced with run_sql.py;
      amounts in EUR, frequencies in claims per policy year
    - SQLite specifics are marked with "SQLite:"
*/


------------------------------------------------------------------------
------------------------------------------------------------------------
-- CHAPTER 0  Setup: indexes and query plans
------------------------------------------------------------------------
------------------------------------------------------------------------

/*
Almost every query joins claims to policies on IDpol. Without an index the
database has to search the other table for every row. EXPLAIN QUERY PLAN shows
how SQLite executes a query, without running it.

The indexes are dropped first, so that the comparison "before / after" is
reproducible when the file is run more than once.
*/

DROP INDEX IF EXISTS idx_policies_idpol;
DROP INDEX IF EXISTS idx_claims_idpol;

-- query plan WITHOUT index
EXPLAIN QUERY PLAN
SELECT COUNT(*)
FROM claims c
LEFT JOIN policies p
    ON c.IDpol = p.IDpol
WHERE p.IDpol IS NULL;

-- run time WITHOUT index (see run time printed by run_sql.py)
SELECT COUNT(*) AS unmatched_claims
FROM claims c
LEFT JOIN policies p
    ON c.IDpol = p.IDpol
WHERE p.IDpol IS NULL;

CREATE INDEX idx_policies_idpol ON policies (IDpol);
CREATE INDEX idx_claims_idpol   ON claims (IDpol);

-- query plan WITH index
EXPLAIN QUERY PLAN
SELECT COUNT(*)
FROM claims c
LEFT JOIN policies p
    ON c.IDpol = p.IDpol
WHERE p.IDpol IS NULL;

-- run time WITH index
SELECT COUNT(*) AS unmatched_claims
FROM claims c
LEFT JOIN policies p
    ON c.IDpol = p.IDpol
WHERE p.IDpol IS NULL;

/*
Results:
- without index: "SCAN c" + "SEARCH p USING AUTOMATIC COVERING INDEX"
  -> SQLite builds a temporary index on policies for this one query and
     throws it away afterwards (about 120 ms)
- with index:    "SCAN c USING COVERING INDEX idx_claims_idpol" +
                 "SEARCH p USING COVERING INDEX idx_policies_idpol"
  -> the stored index is used directly (about 8 ms)
- a lookup of a single policy (WHERE IDpol = ...) drops from a full
  table scan (about 25 ms) to an index search (< 1 ms)

Terms in the query plan:
- SCAN:   reads the whole table row by row
- SEARCH: jumps directly to the matching rows via an index
- AUTOMATIC INDEX: a temporary index SQLite builds for this query only
- COVERING INDEX:  the index alone contains every column the query needs,
                   so the table itself is not read at all
- BLOOM FILTER:    a quick pre-check that skips rows which cannot match

Interpretation:
An index pays off for columns that are joined or filtered on repeatedly.
It is not free: it uses disk space and slows down inserts and updates.
Queries that join an intermediate result (a CTE) cannot use these stored
indexes for the CTE side, so not every query gets faster.
Run times depend on the machine; the plans do not.
*/


------------------------------------------------------------------------
------------------------------------------------------------------------
-- CHAPTER 1  Data quality on the RAW data
------------------------------------------------------------------------
------------------------------------------------------------------------

/*
All checks in this chapter use the raw tables as loaded from the CSV files.
They document WHY the data has to be cleaned before modelling (chapter 2).
*/

------------------------------------------------------------------------
-- 1.1 Table sizes
------------------------------------------------------------------------

-- row counts of both source tables in one result (UNION ALL keeps all rows,
-- UNION would additionally remove duplicate rows)
SELECT 'policies' AS source_table, COUNT(*) AS row_count FROM policies
UNION ALL
SELECT 'claims', COUNT(*) FROM claims;

-- small sample of each table
SELECT *
FROM policies
LIMIT 5;

SELECT *
FROM claims
LIMIT 5;

/*
Results:
- policies: 678,013 rows, 12 columns (one row per policy)
- claims:    26,639 rows,  2 columns (one row per claim: IDpol, ClaimAmount)
*/

------------------------------------------------------------------------
-- 1.2 Missing values, duplicates and value ranges
------------------------------------------------------------------------

-- missing values in the key fields of the policy table
SELECT
    SUM(CASE WHEN IDpol      IS NULL THEN 1 ELSE 0 END) AS missing_id,
    SUM(CASE WHEN Exposure   IS NULL THEN 1 ELSE 0 END) AS missing_exposure,
    SUM(CASE WHEN ClaimNb    IS NULL THEN 1 ELSE 0 END) AS missing_claim_count,
    SUM(CASE WHEN DrivAge    IS NULL THEN 1 ELSE 0 END) AS missing_driver_age,
    SUM(CASE WHEN BonusMalus IS NULL THEN 1 ELSE 0 END) AS missing_bonus_malus
FROM policies;

-- policy IDs that occur more than once (would double-count exposure)
SELECT
    IDpol,
    COUNT(*) AS row_count
FROM policies
GROUP BY IDpol
HAVING COUNT(*) > 1;

-- values outside the technically possible range
SELECT
    SUM(CASE WHEN Exposure <= 0 THEN 1 ELSE 0 END)   AS nonpositive_exposure,
    SUM(CASE WHEN ClaimNb < 0 THEN 1 ELSE 0 END)     AS negative_claim_count,
    SUM(CASE WHEN DrivAge < 18 THEN 1 ELSE 0 END)    AS driver_below_18,
    SUM(CASE WHEN BonusMalus < 50 OR BonusMalus > 230
             THEN 1 ELSE 0 END)                     AS bonus_malus_out_of_range
FROM policies;

/*
Results:
- no missing values in IDpol, Exposure, ClaimNb, DrivAge, BonusMalus
- every policy ID is unique
- no value outside the technically possible range

Interpretation:
The fields are complete and formally valid. This does not yet mean that
they are plausible -> next checks.
*/

------------------------------------------------------------------------
-- 1.3 Plausibility of exposure, claim counts and Bonus-Malus
------------------------------------------------------------------------

-- exposure is the insured share of one year; claim counts per policy
SELECT
    SUM(CASE WHEN Exposure > 1 THEN 1 ELSE 0 END) AS exposure_above_1_year,
    MAX(Exposure)                                 AS max_exposure,
    SUM(CASE WHEN ClaimNb > 4 THEN 1 ELSE 0 END)  AS policies_with_more_than_4_claims,
    MAX(ClaimNb)                                  AS max_claim_count
FROM policies;

-- young drivers with the minimum Bonus-Malus of 50
SELECT
    DrivAge,
    COUNT(*)                                         AS policy_count,
    SUM(CASE WHEN BonusMalus = 50 THEN 1 ELSE 0 END) AS bonus_malus_50,
    ROUND(AVG(CASE WHEN BonusMalus = 50 THEN 1.0 ELSE 0 END), 3) AS share_bonus_malus_50
FROM policies
WHERE DrivAge <= 22
GROUP BY DrivAge
ORDER BY DrivAge;

/*
Results:
- 1,224 policies have an exposure above 1 year (maximum 2.01)
- 9 policies have more than 4 claims (maximum 16)
- 3% to 10% of the drivers aged 18-22 have the minimum Bonus-Malus of 50
  (age 18: 75 of 748 policies)

Interpretation:
- Contracts run for at most one year, so exposure > 1 is a recording error
  -> capped at 1 in chapter 2.
- More than 4 claims within one year is implausible for a private car
  -> examined in 1.6.
- Under the French Bonus-Malus rules a new driver starts at 100 and loses 5%
  per claim-free year; 50 is reached after about 13 years. A Bonus-Malus of
  50 at age 18 is therefore not possible for the driver's own record.
  Possible explanation: the policy carries the record of another person
  (e.g. a parent). Kept in the data, but flagged as an open question.
*/

------------------------------------------------------------------------
-- 1.4 Claims that cannot be linked to a policy
------------------------------------------------------------------------

-- number of claim records without a matching policy
SELECT
    COUNT(*)                AS unmatched_claim_records,
    COUNT(DISTINCT c.IDpol) AS distinct_unmatched_ids,
    ROUND(SUM(c.ClaimAmount), 0) AS unmatched_claim_amount
FROM claims c
LEFT JOIN policies p
    ON c.IDpol = p.IDpol
WHERE p.IDpol IS NULL;

-- how the unmatched claims are distributed over the policy IDs
SELECT
    c.IDpol,
    COUNT(*)                     AS claim_records,
    ROUND(AVG(c.ClaimAmount), 2) AS average_claim_amount,
    MAX(c.ClaimAmount)           AS maximum_claim_amount,
    ROUND(SUM(c.ClaimAmount), 2) AS total_claim_amount
FROM claims c
LEFT JOIN policies p
    ON c.IDpol = p.IDpol
WHERE p.IDpol IS NULL
GROUP BY c.IDpol
ORDER BY claim_records DESC;

-- do the neighbouring policy numbers exist? (policies joined twice:
-- once for IDpol - 1, once for IDpol + 1)
WITH unmatched_ids AS (
    SELECT
        c.IDpol,
        COUNT(*) AS claim_records
    FROM claims c
    LEFT JOIN policies p
        ON c.IDpol = p.IDpol
    WHERE p.IDpol IS NULL
    GROUP BY c.IDpol
)
SELECT
    u.IDpol,
    u.claim_records,
    prev.IDpol   AS previous_id,
    prev.ClaimNb AS previous_claim_count,
    nxt.IDpol    AS next_id,
    nxt.ClaimNb  AS next_claim_count
FROM unmatched_ids u
LEFT JOIN policies prev
    ON prev.IDpol = u.IDpol - 1
LEFT JOIN policies nxt
    ON nxt.IDpol = u.IDpol + 1
ORDER BY u.claim_records DESC;

/*
Results:
- 195 claim records (about 1.3% of the total claim amount) belong to only
  6 policy IDs with 21 to 66 claims each.
- For every one of these IDs both neighbouring policy numbers exist
  (each with 0 claims).

Interpretation:
The 6 IDs are gaps in the policy table, not random mis-keyed numbers.
A single policy with 21-66 claims is not an individual private car risk;
fleets or group contracts are the most likely explanation. Without policy
attributes and exposure they cannot be rated -> excluded in chapter 2.
*/

------------------------------------------------------------------------
-- 1.5 Repeated combinations of policy ID and claim amount
------------------------------------------------------------------------

-- repeated (IDpol, ClaimAmount) pairs, split by policy match status
WITH repeated_claims AS (
    SELECT
        c.IDpol,
        c.ClaimAmount,
        COUNT(*) AS row_count,
        CASE WHEN p.IDpol IS NULL THEN 'Unmatched' ELSE 'Matched' END AS policy_match
    FROM claims c
    LEFT JOIN policies p
        ON c.IDpol = p.IDpol
    GROUP BY c.IDpol, c.ClaimAmount, policy_match
    HAVING COUNT(*) > 1
)
SELECT
    policy_match,
    COUNT(*)       AS repeated_combinations,
    SUM(row_count) AS claim_records_involved
FROM repeated_claims
GROUP BY policy_match;

/*
Results:
- matched claims:   229 repeated (IDpol, amount) pairs covering 464 records
- unmatched claims:  12 repeated pairs covering 32 records

Interpretation:
The table has no claim identifier, so identical amounts for the same policy
cannot be confirmed as duplicates. Standard amounts (e.g. fixed settlements)
make repetitions plausible. They are kept.
*/

------------------------------------------------------------------------
-- 1.6 Policies with many claims: one driver profile?
------------------------------------------------------------------------

-- self-join: pairs of policies with more than 4 claims that share the same
-- driver and vehicle profile (a.IDpol < b.IDpol lists every pair once)
SELECT
    a.IDpol   AS policy_a,
    b.IDpol   AS policy_b,
    a.DrivAge,
    a.BonusMalus,
    a.VehBrand,
    a.Region,
    a.ClaimNb AS claims_a,
    b.ClaimNb AS claims_b
FROM policies a
INNER JOIN policies b
    ON  a.IDpol < b.IDpol
    AND a.DrivAge BETWEEN b.DrivAge - 1 AND b.DrivAge + 1
    AND a.BonusMalus = b.BonusMalus
    AND a.VehBrand   = b.VehBrand
    AND a.Region     = b.Region
WHERE a.ClaimNb > 4
  AND b.ClaimNb > 4
ORDER BY a.IDpol, b.IDpol;

-- all policies with more than 4 claims for reference
SELECT
    IDpol, ClaimNb, Exposure, DrivAge, BonusMalus, VehBrand, Region
FROM policies
WHERE ClaimNb > 4
ORDER BY IDpol;

/*
Results:
- 7 of the 9 policies with more than 4 claims share one profile:
  driver aged 52-53, Bonus-Malus 50, brand B1, region Languedoc-Roussillon,
  with 5 to 16 claims, mostly within 0.07-0.41 policy years.
- Their IDs are far apart (2.2 and 3.25 million).

Interpretation:
Several "policies" with an identical profile and a claim frequency of up to
100 per year describe one large risk (most likely a fleet) rather than
independent private drivers. Together with 1.4 this points to fleet business
that is not represented as individual risks -> excluded in chapter 2.
*/

------------------------------------------------------------------------
-- 1.7 Claim amounts: validity and largest claims
------------------------------------------------------------------------

SELECT
    COUNT(*)                                          AS claim_records,
    SUM(CASE WHEN ClaimAmount IS NULL THEN 1 ELSE 0 END) AS missing_amount,
    SUM(CASE WHEN ClaimAmount <= 0 THEN 1 ELSE 0 END)    AS nonpositive_amount,
    MIN(ClaimAmount)                                  AS min_amount,
    ROUND(AVG(ClaimAmount), 2)                        AS avg_amount,
    MAX(ClaimAmount)                                  AS max_amount
FROM claims;

-- the largest claims together with the driver profile
SELECT
    c.IDpol,
    c.ClaimAmount,
    p.DrivAge,
    p.BonusMalus,
    p.VehBrand,
    p.Region
FROM claims c
INNER JOIN policies p
    ON c.IDpol = p.IDpol
ORDER BY c.ClaimAmount DESC
LIMIT 10;

/*
Results:
- all amounts present and strictly positive; min 1, mean 2,278.54, max 4,075,400.56
- the three claims above 1 million (4.08 / 1.40 / 1.30 million) all belong to
  drivers aged 18-20 with Bonus-Malus 100

Interpretation:
This explains the unusually high average claim amount of the segment
age 18-25 / Bonus-Malus 81-100: three claims dominate the whole segment.
Large claims need separate treatment (capping and loading, see
validation.py and features.py).
*/

------------------------------------------------------------------------
-- 1.8 Do claim counts and claim amounts describe the same claims?
------------------------------------------------------------------------

/*
Pure premium = frequency x severity. Frequency comes from ClaimNb in policies,
severity from the rows in claims. Both must count the same claims,
otherwise frequency x severity does not match the observed claim cost.
*/

-- ClaimNb compared with the number of claim records per policy
WITH cc AS (
    SELECT
        IDpol,
        COUNT(*) AS amount_records
    FROM claims
    GROUP BY IDpol
),
policy_status AS (
    SELECT
        p.IDpol,
        p.ClaimNb,
        COALESCE(cc.amount_records, 0) AS amount_records
    FROM policies p
    LEFT JOIN cc
        ON cc.IDpol = p.IDpol
)
SELECT
    CASE
        WHEN ClaimNb = amount_records THEN 'consistent'
        WHEN amount_records = 0       THEN 'claims without amounts'
        ELSE 'count differs'
    END                 AS status,
    COUNT(*)            AS policy_count,
    SUM(ClaimNb)        AS claim_count,
    SUM(amount_records) AS claim_records_with_amount
FROM policy_status
GROUP BY status
ORDER BY policy_count DESC;

/*
Results:
- 668,896 consistent policies (26,443 claims, each with an amount)
- 9,116 policies with 9,657 claims but no amount at all
- 1 policy with a different count
-> 9,117 inconsistent policies, in line with the dataset documentation.
   Sum of ClaimNb (36,102) / claim records (26,639) = 1.355.
*/

------------------------------------------------------------------------
-- 1.9 Where are the inconsistent policies? Window function
------------------------------------------------------------------------

/*
SUM(...) OVER (ORDER BY IDpol ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
is a running total: for each policy it counts the claim-free policies up to and
including this one. As long as the running total is 0, no claim-free policy has
appeared yet -> these rows form a block of claim-only policies at the start.
*/

WITH flagged AS (
    SELECT
        IDpol,
        ClaimNb,
        Exposure,
        SUM(CASE WHEN ClaimNb = 0 THEN 1 ELSE 0 END) OVER (
            ORDER BY IDpol
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        ) AS claim_free_policies_so_far
    FROM policies
),
cc AS (
    SELECT
        IDpol,
        COUNT(*) AS amount_records
    FROM claims
    GROUP BY IDpol
)
SELECT
    CASE WHEN f.claim_free_policies_so_far = 0
         THEN 'block before first claim-free policy'
         ELSE 'rest of portfolio' END                      AS segment,
    COUNT(*)                                               AS policy_count,
    MIN(f.IDpol)                                           AS first_id,
    MAX(f.IDpol)                                           AS last_id,
    ROUND(SUM(f.Exposure), 1)                              AS exposure,
    SUM(f.ClaimNb)                                         AS claim_count,
    SUM(COALESCE(cc.amount_records, 0))                    AS claim_records_with_amount,
    ROUND(SUM(COALESCE(cc.amount_records, 0)) * 1.0 / SUM(f.ClaimNb), 3)
                                                           AS share_with_amount,
    ROUND(SUM(f.ClaimNb) / SUM(f.Exposure), 4)             AS claim_frequency
FROM flagged f
LEFT JOIN cc
    ON cc.IDpol = f.IDpol
GROUP BY segment;

/*
Results:
                     block (IDpol 1 - 24,951)   rest (from 24,952)
  policies                 9,387                   668,626
  exposure                 4,800 (1.3%)            353,699
  ClaimNb                  9,942 (27.5%)            26,160
  with amount                307 (3%)               26,137 (99.9%)
  claim frequency           2.07                    0.074

Interpretation:
The missing claim amounts are not spread randomly: almost all of them sit in
one block of claim-only policies at the start of the data. This block is not
a sample of the portfolio (it contains only policies with claims) and has an
implausible frequency of 2 claims per year. It inflated the frequency of the
raw data from 0.074 to 0.101 and caused the +31.9% overestimation of the
first pure premium model.

Summary of chapter 1 -> cleaning rules for chapter 2:
1. remove the block of claim-only policies (whole policies, not single rows)
2. remove remaining policies whose ClaimNb differs from the claim records
3. remove policies with more than 4 claims (fleet-like risks, see 1.6)
4. cap exposure at 1 year
5. remove claims without a policy and claims of removed policies
*/


------------------------------------------------------------------------
------------------------------------------------------------------------
-- CHAPTER 2  Cleaning: consistent tables policies_clean / claims_clean
------------------------------------------------------------------------
------------------------------------------------------------------------

/*
The cleaning rules from chapter 1 are applied here once. The result is stored
in two new tables, so that all later analyses read the same cleaned data.
The rules are identical to clean() in data_prep.py; check_sql_cleaning.py
compares both implementations.

Design decisions:
- The raw tables stay untouched: cleaning is documented and reproducible.
- The new tables get explicit keys instead of CREATE TABLE ... AS SELECT,
  because CREATE TABLE AS copies only data and column types, no keys:
    policies_clean.IDpol  PRIMARY KEY  -> unique, automatically indexed
    claims_clean.ClaimID  PRIMARY KEY  -> a claim identifier, which the raw
                                          claims table does not have (1.5)
    claims_clean.IDpol    FOREIGN KEY  -> every claim must belong to a policy
- All statements run in one transaction: either both tables are rebuilt
  completely, or (on an error) nothing changes.

SQLite: foreign keys are only enforced after PRAGMA foreign_keys = ON
(off by default for backwards compatibility). The pragma has no effect
inside a transaction, so it is set before BEGIN.
*/

PRAGMA foreign_keys = ON;

BEGIN TRANSACTION;

DROP TABLE IF EXISTS claims_clean;
DROP TABLE IF EXISTS policies_clean;

CREATE TABLE policies_clean (
    IDpol       INTEGER PRIMARY KEY,
    ClaimNb     INTEGER NOT NULL CHECK (ClaimNb BETWEEN 0 AND 4),
    Exposure    REAL    NOT NULL CHECK (Exposure > 0 AND Exposure <= 1),
    VehPower    INTEGER,
    VehAge      INTEGER,
    DrivAge     INTEGER NOT NULL,
    BonusMalus  INTEGER NOT NULL,
    VehBrand    TEXT,
    VehGas      TEXT,
    Area        TEXT,
    Density     INTEGER,
    Region      TEXT
);

CREATE TABLE claims_clean (
    ClaimID     INTEGER PRIMARY KEY,                 -- generated identifier
    IDpol       INTEGER NOT NULL REFERENCES policies_clean (IDpol),
    ClaimAmount REAL    NOT NULL CHECK (ClaimAmount > 0)
);

-- policies: rules 1-4 from chapter 1
INSERT INTO policies_clean
WITH flagged AS (
    SELECT
        p.*,
        SUM(CASE WHEN p.ClaimNb = 0 THEN 1 ELSE 0 END) OVER (
            ORDER BY p.IDpol
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        ) AS claim_free_policies_so_far
    FROM policies p
),
cc AS (
    SELECT
        IDpol,
        COUNT(*) AS amount_records
    FROM claims
    GROUP BY IDpol
)
SELECT
    CAST(f.IDpol AS INTEGER),          -- stored as REAL by pandas, an ID is an integer
    f.ClaimNb,
    MIN(f.Exposure, 1.0),              -- rule 4: cap exposure at one year (1.3);
                                       -- contracts run for at most one year
    f.VehPower,
    f.VehAge,
    f.DrivAge,
    f.BonusMalus,
    f.VehBrand,
    f.VehGas,
    f.Area,
    f.Density,
    f.Region
FROM flagged f
LEFT JOIN cc
    ON cc.IDpol = f.IDpol
-- rule 1: drop the block of claim-only policies at the start (1.9); it is a
--         selection of claim cases, not a sample of the portfolio
WHERE f.claim_free_policies_so_far > 0
-- rule 2: keep only policies whose ClaimNb equals their number of claim
--         amounts, so that frequency and severity count the same claims (1.8)
  AND f.ClaimNb = COALESCE(cc.amount_records, 0)
-- rule 3: drop policies with more than 4 claims (fleet-like risks, 1.6);
--         excluded instead of capped, otherwise ClaimNb (4) and the number
--         of claim amounts (up to 16) would differ again
  AND f.ClaimNb <= 4;

-- claims: rule 5, keep only claims whose policy was kept (the INNER JOIN drops
-- the 195 claims without a policy and the claims of policies removed above);
-- ClaimID is numbered automatically because it is the INTEGER PRIMARY KEY
INSERT INTO claims_clean (IDpol, ClaimAmount)
SELECT
    c.IDpol,
    c.ClaimAmount
FROM claims c
INNER JOIN policies_clean p
    ON p.IDpol = c.IDpol
ORDER BY c.IDpol;

CREATE INDEX idx_claims_clean_idpol ON claims_clean (IDpol);

COMMIT;

/*
SQLite: MIN(a, b) with two arguments is a scalar function (the smaller value),
with one argument it is the aggregate function. Other databases use LEAST(a, b).
*/

------------------------------------------------------------------------
-- 2.1 Checks of the cleaned tables
------------------------------------------------------------------------

-- raw vs clean: what was removed?
SELECT
    'policies'                       AS item,
    (SELECT COUNT(*) FROM policies)       AS raw,
    (SELECT COUNT(*) FROM policies_clean) AS clean
UNION ALL
SELECT
    'policy years (exposure)',
    (SELECT CAST(ROUND(SUM(Exposure)) AS INTEGER) FROM policies),
    (SELECT CAST(ROUND(SUM(Exposure)) AS INTEGER) FROM policies_clean)
UNION ALL
SELECT
    'claims (ClaimNb)',
    (SELECT SUM(ClaimNb) FROM policies),
    (SELECT SUM(ClaimNb) FROM policies_clean)
UNION ALL
SELECT
    'claim records with amount',
    (SELECT COUNT(*) FROM claims),
    (SELECT COUNT(*) FROM claims_clean)
UNION ALL
SELECT
    'total claim amount',
    (SELECT CAST(ROUND(SUM(ClaimAmount)) AS INTEGER) FROM claims),
    (SELECT CAST(ROUND(SUM(ClaimAmount)) AS INTEGER) FROM claims_clean);

-- consistency: every claim counted in ClaimNb has exactly one amount
WITH cc AS (
    SELECT
        IDpol,
        COUNT(*) AS amount_records
    FROM claims_clean
    GROUP BY IDpol
)
SELECT
    COUNT(*) AS inconsistent_policies
FROM policies_clean p
LEFT JOIN cc
    ON cc.IDpol = p.IDpol
WHERE p.ClaimNb <> COALESCE(cc.amount_records, 0);

-- foreign key check: lists claims whose policy does not exist (expected: none)
PRAGMA foreign_key_check (claims_clean);

/*
Results:
                              raw        clean      removed
  policies                678,013      668,595       1.4%
  policy years            358,499      353,540       1.4%
  ClaimNb                  36,102       26,065
  claim records            26,639       26,065       2.2%
  total claim amount   60,697,931   59,092,708       2.6%

- 0 inconsistent policies: sum of ClaimNb = number of claim records (26,065)
- foreign key check: no rows -> every claim belongs to a policy

Interpretation:
The cleaned tables fulfil the condition frequency and severity need:
both count the same 26,065 claims. The numbers are identical to the Python
cleaning (data_prep.py), see check_sql_cleaning.py.
*/

------------------------------------------------------------------------
-- 2.2 Views with the rating bands
------------------------------------------------------------------------

/*
The rating bands were repeated as CASE blocks in nearly every query of the
first version of this file. A view stores the query once; later queries
select from the view like from a table. The view holds no data of its own,
it is evaluated each time it is used, so it always reflects the current
policies_clean table.

Why this matters: the band limits are defined in exactly one place and are
identical to data_prep.py. A change (e.g. a new Bonus-Malus band) is made
once and applies to every query, and SQL and Python results stay comparable.
Repeated CASE blocks invite small differences between copies, which is how
the first version ended up with bands that differed from the Python code.
*/

DROP VIEW IF EXISTS v_policies_rated;
CREATE VIEW v_policies_rated AS
SELECT
    p.*,
    CASE
        WHEN p.DrivAge <= 25 THEN '18-25'
        WHEN p.DrivAge <= 40 THEN '26-40'
        WHEN p.DrivAge <= 60 THEN '41-60'
        ELSE '61+'
    END AS age_group,
    CASE
        WHEN p.BonusMalus <= 50  THEN '<=50'
        WHEN p.BonusMalus <= 64  THEN '51-64'
        WHEN p.BonusMalus <= 80  THEN '65-80'
        WHEN p.BonusMalus <= 100 THEN '81-100'
        WHEN p.BonusMalus <= 125 THEN '101-125'
        ELSE '>125'
    END AS bm_group,
    -- sort keys, so that groups appear in natural order instead of alphabetically
    CASE
        WHEN p.DrivAge <= 25 THEN 1
        WHEN p.DrivAge <= 40 THEN 2
        WHEN p.DrivAge <= 60 THEN 3
        ELSE 4
    END AS age_order,
    CASE
        WHEN p.BonusMalus <= 50  THEN 1
        WHEN p.BonusMalus <= 64  THEN 2
        WHEN p.BonusMalus <= 80  THEN 3
        WHEN p.BonusMalus <= 100 THEN 4
        WHEN p.BonusMalus <= 125 THEN 5
        ELSE 6
    END AS bm_order
FROM policies_clean p;

-- claims with the rating bands of their policy
DROP VIEW IF EXISTS v_claims_rated;
CREATE VIEW v_claims_rated AS
SELECT
    c.ClaimID,
    c.IDpol,
    c.ClaimAmount,
    p.age_group,
    p.bm_group,
    p.age_order,
    p.bm_order
FROM claims_clean c
INNER JOIN v_policies_rated p
    ON p.IDpol = c.IDpol;

-- check: every policy falls into exactly one band
SELECT
    age_group,
    COUNT(*) AS policy_count
FROM v_policies_rated
GROUP BY age_group, age_order
ORDER BY age_order;

/*
Results: 18-25: 38,482 / 26-40: 233,337 / 41-60: 295,716 / 61+: 101,060 policies,
together 668,595 = all cleaned policies.
*/


------------------------------------------------------------------------
------------------------------------------------------------------------
-- CHAPTER 3  Portfolio metrics and segmentation on the CLEAN data
------------------------------------------------------------------------
------------------------------------------------------------------------

/*
The three building blocks of a tariff, observed directly from the data:

    claim frequency   = claims / policy years            (how often)
    claim severity    = claim amount / claims            (how expensive)
    pure premium      = claim amount / policy years      (= frequency x severity)

These observed values are what the GLMs in main.py, validation.py and
features.py try to reproduce and smooth. Looking at them first shows where
the models have a lot of data and where they must extrapolate.

Method used in every query of this chapter:
policies and claims are aggregated SEPARATELY and joined afterwards on the
segment. Joining claims to policies first and then summing exposure would
count the exposure of a policy once per claim (a policy with 3 claims would
contribute its exposure 3 times) and understate the frequency.

All queries read the views v_policies_rated / v_claims_rated (chapter 2.2).
SQLite: column names are not case-sensitive; claim_count and CLAIM_COUNT are
the same column. Names are therefore chosen to be unique without relying on
upper/lower case.
*/

------------------------------------------------------------------------
-- 3.1 Portfolio overview
------------------------------------------------------------------------

-- one line with the key figures of the whole cleaned portfolio
SELECT
    COUNT(*)                                     AS policy_count,
    ROUND(SUM(Exposure), 0)                      AS policy_years,
    SUM(ClaimNb)                                 AS claim_count,
    ROUND(SUM(ClaimNb) / SUM(Exposure), 4)       AS claim_frequency,
    (SELECT ROUND(AVG(ClaimAmount), 2) FROM claims_clean)
                                                 AS avg_claim_amount,
    ROUND((SELECT SUM(ClaimAmount) FROM claims_clean) / SUM(Exposure), 2)
                                                 AS observed_pure_premium
FROM policies_clean;

/*
Results:
- 668,595 policies, 353,540 policy years, 26,065 claims
- claim frequency 0.0737 (7.4 claims per 100 policy years)
- average claim amount 2,267.13
- observed pure premium 167.15 per policy year

Interpretation:
167.15 is the benchmark for the whole tariff: the pure premiums of all
segments, weighted with their exposure, must add up to this value. The model
in main.py reproduces it (portfolio deviation -0.79%).
On the raw data the frequency was 0.1007; the difference is the block of
claim-only policies removed in chapter 2.
*/

------------------------------------------------------------------------
-- 3.2 Frequency, severity and pure premium by driver age group
------------------------------------------------------------------------

/*
Besides the plain severity, a severity with every claim capped at 50,000 is
shown (MIN(ClaimAmount, 50000)). The comparison shows how much of a
segment's claim cost comes from a few very large claims.
*/

WITH policy_metrics AS (
    SELECT
        age_group,
        age_order,
        COUNT(*)      AS policy_count,
        SUM(Exposure) AS policy_years,
        SUM(ClaimNb)  AS claim_count
    FROM v_policies_rated
    GROUP BY age_group, age_order
),
claim_metrics AS (
    SELECT
        age_group,
        SUM(ClaimAmount)              AS claim_amount,
        SUM(MIN(ClaimAmount, 50000))  AS claim_amount_capped
    FROM v_claims_rated
    GROUP BY age_group
)
SELECT
    p.age_group,
    p.policy_count,
    ROUND(p.policy_years, 0)                          AS policy_years,
    p.claim_count,
    ROUND(p.claim_count / p.policy_years, 4)          AS claim_frequency,
    ROUND(c.claim_amount / p.claim_count, 0)          AS avg_claim_amount,
    ROUND(c.claim_amount_capped / p.claim_count, 0)   AS avg_claim_amount_capped,
    ROUND(c.claim_amount / p.policy_years, 2)         AS observed_pure_premium,
    ROUND(c.claim_amount_capped / p.policy_years, 2)  AS pure_premium_capped
FROM policy_metrics p
INNER JOIN claim_metrics c
    ON c.age_group = p.age_group
ORDER BY p.age_order;

/*
Results:
  age     policies  frequency  avg claim  capped  pure premium  capped
  18-25     38,482     0.1487      5,140   1,997        764.23  296.94
  26-40    233,337     0.0725      2,121   1,752        153.68  126.98
  41-60    295,716     0.0722      1,785   1,679        128.88  121.26
  61+      101,060     0.0608      2,255   1,806        137.18  109.88

Interpretation:
- Young drivers have twice the average claim frequency (0.149 vs 0.074).
- Their average claim amount (5,140) is 2.3 to 2.9 times that of the other groups,
  but with claims capped at 50,000 it is only about 1.1 to 1.2 times as high.
  The severity difference comes almost entirely from a few very large claims
  (the three claims above 1 million, chapter 1.7), not from more expensive
  ordinary claims.
- Their observed pure premium of 764 therefore rests on a handful of claims;
  capped it is 297. How the large-claim excess should be shared between the
  groups is discussed in features.py (uniform vs credibility-weighted loading).
*/

------------------------------------------------------------------------
-- 3.3 Frequency, severity and pure premium by Bonus-Malus group
------------------------------------------------------------------------

WITH policy_metrics AS (
    SELECT
        bm_group,
        bm_order,
        COUNT(*)      AS policy_count,
        SUM(Exposure) AS policy_years,
        SUM(ClaimNb)  AS claim_count
    FROM v_policies_rated
    GROUP BY bm_group, bm_order
),
claim_metrics AS (
    SELECT
        bm_group,
        SUM(ClaimAmount)              AS claim_amount,
        SUM(MIN(ClaimAmount, 50000))  AS claim_amount_capped
    FROM v_claims_rated
    GROUP BY bm_group
)
SELECT
    p.bm_group,
    p.policy_count,
    ROUND(p.policy_years, 0)                          AS policy_years,
    p.claim_count,
    ROUND(p.claim_count / p.policy_years, 4)          AS claim_frequency,
    ROUND(c.claim_amount / p.claim_count, 0)          AS avg_claim_amount,
    ROUND(c.claim_amount_capped / p.claim_count, 0)   AS avg_claim_amount_capped,
    ROUND(c.claim_amount / p.policy_years, 2)         AS observed_pure_premium
FROM policy_metrics p
INNER JOIN claim_metrics c
    ON c.bm_group = p.bm_group
ORDER BY p.bm_order;

/*
Results: see table; frequency rises from 0.051 (<=50) to 0.438 (>125),
the pure premium from 98 to 1,463.

Interpretation:
- Bonus-Malus is the strongest rating factor: the frequency rises more than
  eightfold from the best to the worst class. Bonus-Malus summarises the
  driver's own claim history, so it carries more information than age.
- Severity hardly depends on Bonus-Malus once claims are capped
  (about 1,680-1,930 in the large groups). Bonus-Malus predicts HOW OFTEN
  a driver has an accident, much less HOW EXPENSIVE it is.
- The classes 101-125 (6,907 policies) and >125 (806 policies) are small;
  their values are uncertain (see 3.5).
*/

------------------------------------------------------------------------
-- 3.4 Claim frequency by age and Bonus-Malus as a cross table
------------------------------------------------------------------------

/*
A cross table with age groups as rows and Bonus-Malus groups as columns is
easier to read than 24 rows. SQLite has no PIVOT operator; the standard
replacement is conditional aggregation: one SUM(CASE WHEN ...) per column,
which only adds up the rows of that Bonus-Malus group.
*/

SELECT
    age_group,
    ROUND(SUM(CASE WHEN bm_group = '<=50'    THEN ClaimNb  END)
        / SUM(CASE WHEN bm_group = '<=50'    THEN Exposure END), 3) AS "bm <=50",
    ROUND(SUM(CASE WHEN bm_group = '51-64'   THEN ClaimNb  END)
        / SUM(CASE WHEN bm_group = '51-64'   THEN Exposure END), 3) AS "bm 51-64",
    ROUND(SUM(CASE WHEN bm_group = '65-80'   THEN ClaimNb  END)
        / SUM(CASE WHEN bm_group = '65-80'   THEN Exposure END), 3) AS "bm 65-80",
    ROUND(SUM(CASE WHEN bm_group = '81-100'  THEN ClaimNb  END)
        / SUM(CASE WHEN bm_group = '81-100'  THEN Exposure END), 3) AS "bm 81-100",
    ROUND(SUM(CASE WHEN bm_group = '101-125' THEN ClaimNb  END)
        / SUM(CASE WHEN bm_group = '101-125' THEN Exposure END), 3) AS "bm 101-125",
    ROUND(SUM(CASE WHEN bm_group = '>125'    THEN ClaimNb  END)
        / SUM(CASE WHEN bm_group = '>125'    THEN Exposure END), 3) AS "bm >125"
FROM v_policies_rated
GROUP BY age_group, age_order
ORDER BY age_order;

/*
Results:
  age      <=50   51-64  65-80  81-100  101-125   >125
  18-25   0.101   0.059  0.070   0.165    0.375  0.458
  26-40   0.043   0.065  0.090   0.125    0.309  0.366
  41-60   0.056   0.117  0.136   0.153    0.350  0.429
  61+     0.045   0.140  0.166   0.153    0.379  0.643

Interpretation:
- Within every age group the frequency rises with the Bonus-Malus class.
- The same Bonus-Malus class means different things at different ages.
  For a young driver Bonus-Malus 81-100 is the normal starting level
  (new drivers start at 100); for a 41-60 year old it means past claims.
  In the class 51-64, drivers aged 41-60 therefore have twice the frequency
  of drivers aged 18-25 (0.117 vs 0.059). A model with separate age and
  Bonus-Malus factors cannot represent this; an age x Bonus-Malus
  interaction would be the next model step.
- Young drivers with Bonus-Malus <=50 have a frequency of 0.101, more than
  twice the value of the other age groups in that class. This fits the
  implausible Bonus-Malus 50 at age 18-20 found in chapter 1.3.
*/

------------------------------------------------------------------------
-- 3.5 Observed pure premium per tariff cell and its reliability
------------------------------------------------------------------------

/*
The observed pure premium of a cell is only meaningful if the cell has
enough claims. The classical limited-fluctuation credibility standard asks
for 1,082 claims: then the observed claim count lies within +-5% of its
expected value with 90% probability ((1.645 / 0.05)^2 = 1,082).
Cells with fewer claims get a partial credibility Z = sqrt(claims / 1,082).

The LEFT JOIN keeps cells without any claim (they would disappear with an
INNER JOIN), COALESCE turns their missing claim amount into 0.

SQLite: SQRT() requires SQLite 3.35+ compiled with math functions, which is
the case for the SQLite bundled with current Python versions.
*/

WITH policy_metrics AS (
    SELECT
        age_group, age_order, bm_group, bm_order,
        COUNT(*)      AS policy_count,
        SUM(Exposure) AS policy_years,
        SUM(ClaimNb)  AS claim_count
    FROM v_policies_rated
    GROUP BY age_group, age_order, bm_group, bm_order
),
claim_metrics AS (
    SELECT
        age_group, bm_group,
        SUM(ClaimAmount) AS claim_amount
    FROM v_claims_rated
    GROUP BY age_group, bm_group
)
SELECT
    p.age_group,
    p.bm_group,
    p.policy_count,
    ROUND(p.policy_years, 0)                                 AS policy_years,
    p.claim_count,
    ROUND(COALESCE(c.claim_amount, 0) / p.policy_years, 0)   AS observed_pure_premium,
    ROUND(MIN(1.0, SQRT(p.claim_count / 1082.0)), 2)         AS credibility_z,
    CASE
        WHEN p.claim_count >= 1082 THEN 'full'
        WHEN p.claim_count >= 300  THEN 'partial'
        ELSE 'low'
    END                                                      AS reliability
FROM policy_metrics p
LEFT JOIN claim_metrics c
    ON c.age_group = p.age_group
   AND c.bm_group  = p.bm_group
ORDER BY p.age_order, p.bm_order;

/*
Results (selection):
  cell                 policies  claims  observed PP     Z    reliability
  26-40 / <=50           68,506   1,694         78    1.00   full
  41-60 / <=50          223,526   7,092        101    1.00   full
  18-25 / 81-100         23,769   1,492      1,151    1.00   full
  18-25 / >125              279      56      2,898    0.23   low
  61+   / >125               72      25      1,154    0.15   low
  -> 9 of 24 cells have full credibility, 9 have fewer than 300 claims.

Interpretation:
- Even a fully credible cell can be distorted by single large claims:
  18-25 / 81-100 has enough claims for a reliable FREQUENCY, but its pure
  premium of 1,151 is dominated by the three claims above 1 million. The
  credibility standard above is about claim counts, not claim amounts.
- Cells with low credibility (e.g. 61+ / >125 with 25 claims) should not be
  priced on their own experience. A GLM solves this by combining the age
  factor and the Bonus-Malus factor, each estimated from many cells.
  This is the main reason to use a model instead of the observed table.
*/


