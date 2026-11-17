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
-- LEGACY QUERIES (raw data) - revised in the next packages
-- CHAPTER 3 and 4 will replace the following sections and run on the
-- cleaned tables. Kept here unchanged until then.
------------------------------------------------------------------------
------------------------------------------------------------------------
------------------------------------------------------------------------
-- 2 Portfolio metrics
------------------------------------------------------------------------

-- Summarize the size of the insurance portfolio and its
-- total exposure and reported claim count. 

SELECT
    COUNT(*) AS policy_count,
    SUM(Exposure) AS total_exposure,
    SUM(ClaimNb) AS total_claim_count,
    AVG(Exposure) AS avg_exposure_per_policy,
    SUM(ClaimNb) * 1.0 / SUM(Exposure) AS 
    claim_frequency
FROM policies;

/*
Result:

-Number of policies is 678,013
-total exposure is 358499.45 
(rounded to 2 decimals)
-total claim count is 36,102
-average exposure per policy is 0.5287
(rounded to 4 decimals)
-claim frequency is 0.1007
(rounded to 4 decimals)
*/


---------------------------------------------------------
-- Portfolio metrics by driver age group.
-- The CTE assigns risk groups before aggregating portfolio metrics.

WITH classified_policies AS (
    SELECT
        Exposure,
        ClaimNb,
        CASE
            WHEN DrivAge BETWEEN 18 AND 25 THEN '18-25'
            WHEN DrivAge BETWEEN 26 AND 40 THEN '26-40'
            WHEN DrivAge BETWEEN 41 AND 60 THEN '41-60'
            WHEN DrivAge >= 61 THEN '61+'
            ELSE 'Other / missing'
        END AS age_group
    FROM policies
)
SELECT
    age_group,
    COUNT(*) AS policy_count,
    SUM(Exposure) AS total_exposure,
    SUM(ClaimNb) AS total_claim_count,
    SUM(ClaimNb) * 1.0 / SUM(Exposure) AS claim_frequency
FROM classified_policies
GROUP BY age_group
ORDER BY
    CASE age_group
        WHEN '18-25' THEN 1
        WHEN '26-40' THEN 2
        WHEN '41-60' THEN 3
        WHEN '61+' THEN 4
        ELSE 5
    END;

--remark: each policy can be associated to our
--defined age groups / no missing policies detected


----------------------------------------------------------

-- Portfolio metrics by bonus-malus group.
-- The CTE assigns risk groups before aggregating portfolio metrics.

WITH classified_policies AS (
    SELECT
        Exposure,
        ClaimNb,
        CASE
            WHEN BonusMalus <= 50 THEN '<=50'
            WHEN BonusMalus <= 75 THEN '51-75'
            WHEN BonusMalus <= 100 THEN '76-100'
            WHEN BonusMalus <= 125 THEN '101-125'
            WHEN BonusMalus > 125 THEN '>125'
            ELSE 'Other / missing'
        END AS bm_group
    FROM policies
)
SELECT
    bm_group,
    COUNT(*) AS policy_count,
    SUM(Exposure) AS total_exposure,
    SUM(ClaimNb) AS total_claim_count,
    SUM(ClaimNb) * 1.0 / SUM(Exposure) AS claim_frequency
FROM classified_policies
GROUP BY bm_group
ORDER BY
    CASE bm_group
        WHEN '<=50' THEN 1
        WHEN '51-75' THEN 2
        WHEN '76-100' THEN 3
        WHEN '101-125' THEN 4
        WHEN '>125' THEN 5
        ELSE 6
    END;

--remark: each policy can be associated to our
--defined bm groups / no missing policies detected



-------------------------------------------------------------------------
-- Observed claim severity across all claim records.
-- Establish a baseline before separating matched and unmatched claims.

SELECT
    COUNT(*) AS claim_record_count,
    SUM(ClaimAmount) AS total_claim_amount,
    AVG(ClaimAmount) AS avg_claim_amount,
    MIN(ClaimAmount) AS min_claim_amount,
    MAX(ClaimAmount) AS max_claim_amount
FROM claims;

/*
Result:

-Number of claims is 26,639
-total claim amount is 60.70 Mio 
(rounded to 2 decimals)
-average claim amount is 2,278.54 
(rounded to 2 decimals)
-min claim = 1 ; max claim = 4.08 Mio
(rounded to 2 decimals)
*/

-------------------------------------------------------------------------

-- Compare claim amounts by policy-matching status.
-- Unmatched claims cannot be assigned to age or bonus-malus groups.


SELECT
    CASE
        WHEN p.IDpol IS NULL THEN 'Unmatched'
        ELSE 'Matched'
    END AS policy_match,
    COUNT(*) AS claim_record_count,
    SUM(c.ClaimAmount) AS total_claim_amount,
    AVG(c.ClaimAmount) AS avg_claim_amount,
    MIN(c.ClaimAmount) AS min_claim_amount,
    MAX(c.ClaimAmount) AS max_claim_amount
FROM claims c
LEFT JOIN policies p
    ON c.IDpol = p.IDpol
GROUP BY policy_match
ORDER BY
    CASE policy_match
        WHEN 'Matched' THEN 1
        ELSE 2
    END;


-------------------------------------------------------------------------
-- Observed claim severity by driver age group.
-- Only claims matched to a policy can be assigned to an age group.


WITH classified_policies AS (
    SELECT
        IDpol,
        CASE
            WHEN DrivAge BETWEEN 18 AND 25 THEN '18-25'
            WHEN DrivAge BETWEEN 26 AND 40 THEN '26-40'
            WHEN DrivAge BETWEEN 41 AND 60 THEN '41-60'
            WHEN DrivAge >= 61 THEN '61+'
            ELSE 'Other / missing'
        END AS age_group
    FROM policies
)
SELECT
    p.age_group,
    COUNT(*) AS claim_record_count,
    SUM(c.ClaimAmount) AS total_claim_amount,
    AVG(c.ClaimAmount) AS avg_claim_amount
FROM claims c
INNER JOIN classified_policies p
    ON c.IDpol = p.IDpol
GROUP BY p.age_group
ORDER BY
    CASE p.age_group
        WHEN '18-25' THEN 1
        WHEN '26-40' THEN 2
        WHEN '41-60' THEN 3
        WHEN '61+' THEN 4
        ELSE 5
    END;


-------------------------------------------------------------------------
-- Observed claim severity by bonus-malus group.
-- Only claims matched to a policy can be assigned to a bonus-malus group.


WITH classified_policies AS (
    SELECT
        IDpol,
        CASE
            WHEN BonusMalus <= 50 THEN '<=50'
            WHEN BonusMalus <= 75 THEN '51-75'
            WHEN BonusMalus <= 100 THEN '76-100'
            WHEN BonusMalus <= 125 THEN '101-125'
            WHEN BonusMalus > 125 THEN '>125'
            ELSE 'Other / missing'
        END AS bm_group
    FROM policies
)
SELECT
    p.bm_group,
    COUNT(*) AS claim_record_count,
    SUM(c.ClaimAmount) AS total_claim_amount,
    AVG(c.ClaimAmount) AS avg_claim_amount
FROM claims c
INNER JOIN classified_policies p
    ON c.IDpol = p.IDpol
GROUP BY p.bm_group
ORDER BY
    CASE p.bm_group
        WHEN '<=50' THEN 1
        WHEN '51-75' THEN 2
        WHEN '76-100' THEN 3
        WHEN '101-125' THEN 4
        WHEN '>125' THEN 5
        ELSE 6
    END;


-------------------------------------------------------------------------
-- Observed claim cost and frequency metrics by driver age group.
-- Aggregate policy and claim data separately to prevent join duplication.

WITH classified_policies AS (
    SELECT
        IDpol,
        Exposure,
        ClaimNb,
        CASE
            WHEN DrivAge BETWEEN 18 AND 25 THEN '18-25'
            WHEN DrivAge BETWEEN 26 AND 40 THEN '26-40'
            WHEN DrivAge BETWEEN 41 AND 60 THEN '41-60'
            WHEN DrivAge >= 61 THEN '61+'
            ELSE 'Other / missing'
        END AS age_group
    FROM policies
),
policy_metrics AS (
    SELECT
        age_group,
        COUNT(*) AS policy_count,
        SUM(Exposure) AS total_exposure,
        SUM(ClaimNb) AS total_claim_count
    FROM classified_policies
    GROUP BY age_group
),
claim_metrics AS (
    SELECT
        p.age_group,
        COUNT(*) AS claim_record_count,
        SUM(c.ClaimAmount) AS total_claim_amount
    FROM claims c
    INNER JOIN classified_policies p
        ON c.IDpol = p.IDpol
    GROUP BY p.age_group
)
SELECT
    p.age_group,
    p.policy_count,
    p.total_exposure,
    p.total_claim_count,
    p.total_claim_count * 1.0 / p.total_exposure
        AS claim_frequency,
    c.claim_record_count,
    c.total_claim_amount,
    c.total_claim_amount / c.claim_record_count
        AS avg_claim_amount,
    c.claim_record_count * 1.0 / p.total_exposure
        AS severity_record_frequency,
    c.total_claim_amount / p.total_exposure
        AS observed_pure_premium
FROM policy_metrics p
INNER JOIN claim_metrics c
    ON p.age_group = c.age_group
ORDER BY
    CASE p.age_group
        WHEN '18-25' THEN 1
        WHEN '26-40' THEN 2
        WHEN '41-60' THEN 3
        WHEN '61+' THEN 4
        ELSE 5
    END;

/*
Remark:
This table shows many important key aspects for an evaluation of the
age group categories. The pure premium observation indicates a much 
higher amount with 758.40 vs. ca. 130-150 in other age groups.

This follows from severity data and avg. claim amount, which are 
considerably higher compared to the other age groups.Area
*/


-------------------------------------------------------------------------
-- Observed claim cost and frequency metrics by bonus-malus group.
-- Aggregate policy and claim data separately to prevent join duplication.

WITH classified_policies AS (
    SELECT
        IDpol,
        Exposure,
        ClaimNb,
        CASE
            WHEN BonusMalus <= 50 THEN '<=50'
            WHEN BonusMalus <= 75 THEN '51-75'
            WHEN BonusMalus <= 100 THEN '76-100'
            WHEN BonusMalus <= 125 THEN '101-125'
            WHEN BonusMalus > 125 THEN '>125'
            ELSE 'Other / missing'
        END AS bm_group
    FROM policies
),
policy_metrics AS (
    SELECT
        bm_group,
        COUNT(*) AS policy_count,
        SUM(Exposure) AS total_exposure,
        SUM(ClaimNb) AS total_claim_count
    FROM classified_policies
    GROUP BY bm_group
),
claim_metrics AS (
    SELECT
        p.bm_group,
        COUNT(*) AS claim_record_count,
        SUM(c.ClaimAmount) AS total_claim_amount
    FROM claims c
    INNER JOIN classified_policies p
        ON c.IDpol = p.IDpol
    GROUP BY p.bm_group
)
SELECT
    p.bm_group,
    p.policy_count,
    p.total_exposure,
    p.total_claim_count,
    p.total_claim_count * 1.0 / p.total_exposure
        AS claim_frequency,
    c.claim_record_count,
    c.total_claim_amount,
    c.total_claim_amount / c.claim_record_count
        AS avg_claim_amount,
    c.claim_record_count * 1.0 / p.total_exposure
        AS severity_record_frequency,
    c.total_claim_amount / p.total_exposure
        AS observed_pure_premium
FROM policy_metrics p
INNER JOIN claim_metrics c
    ON p.bm_group = c.bm_group
ORDER BY
    CASE p.bm_group
        WHEN '<=50' THEN 1
        WHEN '51-75' THEN 2
        WHEN '76-100' THEN 3
        WHEN '101-125' THEN 4
        WHEN '>125' THEN 5
        ELSE 6
    END;

/*
Remark:
This table shows many important key aspects for an evaluation of the
BM-Group categories. The pure premium amount is clearly correlated 
to the BM-Group with rising value as the BM-number ascends.

This behaviour is plausible with the tariff examples from different 
insurance companies.

One should be careful with the smaller BM-Groups '101-125' and '>125'
since the policy count is exceptionally small compared to the other
BM-Groups (807 and 6987 vs. 100,000 - 380,000). 
*/



------------------------------------------------------------------------
-- 3 Risk and premium segmentation
------------------------------------------------------------------------

-- Analyze claim frequency across combined age and bonus-malus segments.
-- This reveals patterns that separate one-dimensional summaries may hide.

WITH classified_policies AS (
    SELECT
        Exposure,
        ClaimNb,
        CASE
            WHEN DrivAge BETWEEN 18 AND 25 THEN '18-25'
            WHEN DrivAge BETWEEN 26 AND 40 THEN '26-40'
            WHEN DrivAge BETWEEN 41 AND 60 THEN '41-60'
            WHEN DrivAge >= 61 THEN '61+'
            ELSE 'Other / missing'
        END AS age_group,
        CASE
            WHEN BonusMalus <= 50 THEN '<=50'
            WHEN BonusMalus <= 75 THEN '51-75'
            WHEN BonusMalus <= 100 THEN '76-100'
            WHEN BonusMalus <= 125 THEN '101-125'
            WHEN BonusMalus > 125 THEN '>125'
            ELSE 'Other / missing'
        END AS bm_group
    FROM policies
)
SELECT
    age_group,
    bm_group,
    COUNT(*) AS policy_count,
    SUM(Exposure) AS total_exposure,
    SUM(ClaimNb) AS total_claim_count,
    SUM(ClaimNb) * 1.0 / SUM(Exposure) AS claim_frequency
FROM classified_policies
GROUP BY
    age_group,
    bm_group
ORDER BY
    CASE age_group
        WHEN '18-25' THEN 1
        WHEN '26-40' THEN 2
        WHEN '41-60' THEN 3
        WHEN '61+' THEN 4
        ELSE 5
    END,
    CASE bm_group
        WHEN '<=50' THEN 1
        WHEN '51-75' THEN 2
        WHEN '76-100' THEN 3
        WHEN '101-125' THEN 4
        WHEN '>125' THEN 5
        ELSE 6
    END;

/*
Remark:

Inside each age group it can be observed, that claim freq. is
ascending with higher BM-number. 

Again one has to be cautious with interpretations on 
combinations with small policy counts e.g. age 61+ with 
BM-'>125' has only 73 policies.  
*/



------------------------------------------------------------------------
-- Calculate average claim amount across combined age and bm segments
-- Only matched claim records are used for the segments

WITH classified_policies AS (
    SELECT
        IDpol,
        CASE
            WHEN DrivAge BETWEEN 18 AND 25 THEN '18-25'
            WHEN DrivAge BETWEEN 26 AND 40 THEN '26-40'
            WHEN DrivAge BETWEEN 41 AND 60 THEN '41-60'
            WHEN DrivAge >= 61 THEN '61+'
            ELSE 'Other / missing'
        END AS age_group,
        CASE
            WHEN BonusMalus <= 50 THEN '<=50'
            WHEN BonusMalus <= 75 THEN '51-75'
            WHEN BonusMalus <= 100 THEN '76-100'
            WHEN BonusMalus <= 125 THEN '101-125'
            WHEN BonusMalus > 125 THEN '>125'
            ELSE 'Other / missing'
        END AS bm_group
    FROM policies
)
SELECT
    p.age_group,
    p.bm_group,
    COUNT(*) AS claim_record_count,
    SUM(c.ClaimAmount) AS total_claim_amount,
    AVG(c.ClaimAmount) AS avg_claim_amount
FROM claims c
INNER JOIN classified_policies p
    ON c.IDpol = p.IDpol
GROUP BY
    p.age_group,
    p.bm_group
ORDER BY
    CASE p.age_group
        WHEN '18-25' THEN 1
        WHEN '26-40' THEN 2
        WHEN '41-60' THEN 3
        WHEN '61+' THEN 4
        ELSE 5
    END,
    CASE p.bm_group
        WHEN '<=50' THEN 1
        WHEN '51-75' THEN 2
        WHEN '76-100' THEN 3
        WHEN '101-125' THEN 4
        WHEN '>125' THEN 5
        ELSE 6
    END;



------------------------------------------------------------------------
-- Calculate observed pure premium across combined age and bonus-malus segments.
-- Aggregate policy and claim data separately to prevent join duplication.
-- Only matched claim records can be assigned to the respective risk segments.

WITH classified_policies AS (
    SELECT
        IDpol,
        Exposure,
        ClaimNb,
        CASE
            WHEN DrivAge BETWEEN 18 AND 25 THEN '18-25'
            WHEN DrivAge BETWEEN 26 AND 40 THEN '26-40'
            WHEN DrivAge BETWEEN 41 AND 60 THEN '41-60'
            WHEN DrivAge >= 61 THEN '61+'
            ELSE 'Other / missing'
        END AS age_group,
        CASE
            WHEN BonusMalus <= 50 THEN '<=50'
            WHEN BonusMalus <= 75 THEN '51-75'
            WHEN BonusMalus <= 100 THEN '76-100'
            WHEN BonusMalus <= 125 THEN '101-125'
            WHEN BonusMalus > 125 THEN '>125'
            ELSE 'Other / missing'
        END AS bm_group
    FROM policies
),
policy_metrics AS (
    SELECT
        age_group,
        bm_group,
        COUNT(*) AS policy_count,
        SUM(Exposure) AS total_exposure,
        SUM(ClaimNb) AS total_claim_count
    FROM classified_policies
    GROUP BY age_group, bm_group
),
claim_metrics AS (
    SELECT
        p.age_group,
        p.bm_group,
        COUNT(*) AS claim_record_count,
        SUM(c.ClaimAmount) AS total_claim_amount
    FROM claims c
    INNER JOIN classified_policies p
        ON c.IDpol = p.IDpol
    GROUP BY p.age_group, p.bm_group
)
SELECT
    p.age_group,
    p.bm_group,
    p.policy_count,
    p.total_exposure,
    p.total_claim_count,
    p.total_claim_count * 1.0 / p.total_exposure
        AS claim_frequency,
    c.claim_record_count,
    c.total_claim_amount,
    c.total_claim_amount / c.claim_record_count
        AS avg_claim_amount,
    c.claim_record_count * 1.0 / p.total_exposure
        AS severity_record_frequency,
    c.total_claim_amount / p.total_exposure
        AS observed_pure_premium
FROM policy_metrics p
INNER JOIN claim_metrics c
    ON p.age_group = c.age_group
    AND p.bm_group = c.bm_group
ORDER BY
    CASE p.age_group
        WHEN '18-25' THEN 1
        WHEN '26-40' THEN 2
        WHEN '41-60' THEN 3
        WHEN '61+' THEN 4
        ELSE 5
    END,
    CASE p.bm_group
        WHEN '<=50' THEN 1
        WHEN '51-75' THEN 2
        WHEN '76-100' THEN 3
        WHEN '101-125' THEN 4
        WHEN '>125' THEN 5
        ELSE 6
    END;

/*
Remark:
The segmentation reveals an exceptional behaviour of the
pure premium amounts. This wasn't completly visible in
the seperate observations of age group and BM-Groups. 

In particular there are three special combinations, where one 
has to be cautious for further interpretations:


1. age '18-25' + bm '76-100' --> 6363 claim amount with 1730 claims
is a relatively big group. The deviation of this group in comparison 
to the other segmentations is too high to be left unnoticed. A reason 
for this amount isn't clear at the moment.


2. the age group '26-40' has no monotonicity in the avg. claim amount, which
means that bm doesn't influence the avg. claim amount in this age group.


3. age groups '41-60' and '61+' show the same effect described in 2., so 
that we can't see a bm influence for the avg. claim amount either. 
*/

------------------------------------------------------------------------



------------------------------------------------------------------------
-- 4 Further analysis of risk segments ... (in progress)
------------------------------------------------------------------------

-- Rank combined age and bonus-malus segments by observed pure premium.
-- RANK() assigns a ranking based on the observed claim cost per exposure unit.
-- Policy and claim data are aggregated separately to prevent join duplication.

WITH classified_policies AS (
    SELECT
        IDpol,
        Exposure,
        CASE
            WHEN DrivAge BETWEEN 18 AND 25 THEN '18-25'
            WHEN DrivAge BETWEEN 26 AND 40 THEN '26-40'
            WHEN DrivAge BETWEEN 41 AND 60 THEN '41-60'
            WHEN DrivAge >= 61 THEN '61+'
            ELSE 'Other / missing'
        END AS age_group,
        CASE
            WHEN BonusMalus <= 50 THEN '<=50'
            WHEN BonusMalus <= 75 THEN '51-75'
            WHEN BonusMalus <= 100 THEN '76-100'
            WHEN BonusMalus <= 125 THEN '101-125'
            WHEN BonusMalus > 125 THEN '>125'
            ELSE 'Other / missing'
        END AS bm_group
    FROM policies
),
policy_metrics AS (
    SELECT
        age_group,
        bm_group,
        COUNT(*) AS policy_count,
        SUM(Exposure) AS total_exposure
    FROM classified_policies
    GROUP BY age_group, bm_group
),
claim_metrics AS (
    SELECT
        p.age_group,
        p.bm_group,
        COUNT(*) AS claim_record_count,
        SUM(c.ClaimAmount) AS total_claim_amount
    FROM claims c
    INNER JOIN classified_policies p
        ON c.IDpol = p.IDpol
    GROUP BY p.age_group, p.bm_group
),
pure_premium_metrics AS (
    SELECT
        p.age_group,
        p.bm_group,
        p.policy_count,
        p.total_exposure,
        c.claim_record_count,
        c.total_claim_amount,
        c.total_claim_amount / p.total_exposure
            AS observed_pure_premium
    FROM policy_metrics p
    INNER JOIN claim_metrics c
        ON p.age_group = c.age_group
        AND p.bm_group = c.bm_group
)
SELECT
    age_group,
    bm_group,
    policy_count,
    claim_record_count,
    observed_pure_premium,
    RANK() OVER (
        ORDER BY observed_pure_premium DESC
    ) AS premium_rank
FROM pure_premium_metrics
ORDER BY premium_rank;




------------------------------------------------------------------------
-- Compare policy and claim record counts across age and bonus-malus segments.
-- The results help identify small segments that may produce unstable average claim amounts.

WITH classified_policies AS (
    SELECT
        IDpol,
        Exposure,
        CASE
            WHEN DrivAge BETWEEN 18 AND 25 THEN '18-25'
            WHEN DrivAge BETWEEN 26 AND 40 THEN '26-40'
            WHEN DrivAge BETWEEN 41 AND 60 THEN '41-60'
            WHEN DrivAge >= 61 THEN '61+'
            ELSE 'Other / missing'
        END AS age_group,
        CASE
            WHEN BonusMalus <= 50 THEN '<=50'
            WHEN BonusMalus <= 75 THEN '51-75'
            WHEN BonusMalus <= 100 THEN '76-100'
            WHEN BonusMalus <= 125 THEN '101-125'
            WHEN BonusMalus > 125 THEN '>125'
            ELSE 'Other / missing'
        END AS bm_group
    FROM policies
),
policy_metrics AS (
    SELECT
        age_group,
        bm_group,
        COUNT(*) AS policy_count,
        SUM(Exposure) AS total_exposure
    FROM classified_policies
    GROUP BY age_group, bm_group
),
claim_metrics AS (
    SELECT
        p.age_group,
        p.bm_group,
        COUNT(*) AS claim_record_count,
        AVG(c.ClaimAmount) AS avg_claim_amount
    FROM claims c
    INNER JOIN classified_policies p
        ON c.IDpol = p.IDpol
    GROUP BY p.age_group, p.bm_group
)
SELECT
    p.age_group,
    p.bm_group,
    p.policy_count,
    ROUND(p.total_exposure, 2) AS total_exposure,
    COALESCE(c.claim_record_count, 0) AS claim_record_count,
    ROUND(c.avg_claim_amount, 2) AS avg_claim_amount
FROM policy_metrics p
LEFT JOIN claim_metrics c
    ON p.age_group = c.age_group
    AND p.bm_group = c.bm_group
ORDER BY
    CASE p.age_group
        WHEN '18-25' THEN 1
        WHEN '26-40' THEN 2
        WHEN '41-60' THEN 3
        WHEN '61+' THEN 4
        ELSE 5
    END,
    CASE p.bm_group
        WHEN '<=50' THEN 1
        WHEN '51-75' THEN 2
        WHEN '76-100' THEN 3
        WHEN '101-125' THEN 4
        WHEN '>125' THEN 5
        ELSE 6
    END;




------------------------------------------------------------------------

