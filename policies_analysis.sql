/*
Purpose:
Explore and analyze insurance portfolio and claims data using SQL.
The queries cover data inspection, quality checks, portfolio metrics,
and risk segmentation to support pricing analysis.

The queries are organized into thematic sections and can be executed
individually. The underlying data is loaded from CSV files into SQLite
tables and can also be accessed through the Python analysis script.
*/

------------------------------------------------------------------------
-- 5 Chapter analysis
------------------------------------------------------------------------

--1. Data overview and data quality

--initial inspection of the source tables to understand
--their structure and size before performing data analysis


--policies: 678,013 rows ; 12 columns
--claims:    26,639 rows ;  2 columns

--inspect a small sample of each table
SELECT *
FROM policies
LIMIT 5;

SELECT *
FROM claims
LIMIT 5;

------------------------------------------------------------------------
--1.1 Check for missing values in key analytical fields
-- in the policy table


SELECT
    'policies' AS source_table,
    SUM(CASE WHEN IDpol is NULL THEN 1 ELSE 0 END) AS missing_id,
    SUM(CASE WHEN Exposure is NULL THEN 1 ELSE 0 END) AS missing_exposure,
    SUM(CASE WHEN ClaimNb is NULL THEN 1 ELSE 0 END) AS missing_claim_count,
    SUM(CASE WHEN DrivAge is NULL THEN 1 ELSE 0 END) AS missing_driver_age,
    SUM(CASE WHEN BonusMalus is NULL THEN 1 ELSE 0 END) AS missing_bonus_malus
FROM policies;

/*
Results:
- no missing values in IDpol, Exposure, ClaimNb, DrivAge,
  BonusMalus in policies table

Interpretation:
The checks didn't identify issues with our 5 core fields 
of interest for the upcoming analysis. 

This however doesn't guarantee overall data quality accross
the entire database.
*/

------------------------------------------------------------------------
--1.2 Check whether policy IDs are unique in the policy table
-- multiple rows per policy could impact portfolio metrics.

SELECT
    IDpol,
    COUNT(*) AS row_count
FROM policies
GROUP BY IDpol
HAVING COUNT(*) > 1
ORDER BY row_count DESC;

/*
Results:
- empty table
- no duplicate policy IDs found

Interpretation:
Each policy ID occurs only once in the policies table.
*/

------------------------------------------------------------------------
--1.3 Identify invalid values in key numeric fields

SELECT
    SUM(CASE WHEN Exposure <= 0 THEN 1 ELSE 0 END) AS nonpositive_exposure,
    SUM(CASE WHEN ClaimNb < 0 THEN 1 ELSE 0 END) AS negative_claim_count,
    SUM(CASE WHEN DrivAge <= 0 THEN 1 ELSE 0 END) AS invalid_driver_age,
    SUM(CASE WHEN BonusMalus < 50 OR BonusMalus > 230
             THEN 1 ELSE 0 END) AS bonus_malus_out_of_range
FROM policies;

/*
Results:
- no invalid values detected in checked fields

Interpretation:
Exposure, claim counts, driver age and bonus-malus values
satisfy the defined plausibility checks.
*/

------------------------------------------------------------------------
--1.4 Identify claims that can't be linked to a policy

SELECT
    COUNT(*) AS unmatched_claims
FROM claims c
LEFT JOIN policies p
    ON c.IDpol = p.IDpol
WHERE p.IDpol IS NULL;

/*
Results:
- 195 claims have no matching policy ID.

Interpretation:
These records can't be linked to the policy table and
should be investigated before using the attributes in 
further analysis.
*/


--1.5 Checking for occuring combinations and
-- matching of claim amounts with IDpol

/*
Remark:

Investigate repeated policy ID and claim amount 
combinations among claims that can / can't be matched to
a policy. Repeated comb. aren't necessarily duplicats,
as the table contains no unique claim identifier
*/

--shows repeated policy ID and claim amount combinations
--across all claims (including policy match status)
WITH repeated_claims AS (
    SELECT
        c.IDpol,
        c.ClaimAmount,
        COUNT(*) AS row_count,
        CASE
            WHEN p.IDpol IS NULL THEN 'Unmatched'
            ELSE 'Matched'
        END AS policy_match
    FROM claims c
    LEFT JOIN policies p
        ON c.IDpol = p.IDpol
    GROUP BY c.IDpol, c.ClaimAmount, policy_match
    HAVING COUNT(*) > 1
)
SELECT *
FROM repeated_claims
ORDER BY row_count DESC, IDpol;




--counts repeated comb. without a matching policy ID
WITH repeated_claims AS (
    SELECT
        c.IDpol,
        c.ClaimAmount,
        COUNT(*) AS row_count,
        CASE
            WHEN p.IDpol IS NULL THEN 'Unmatched'
            ELSE 'Matched'
        END AS policy_match
    FROM claims c
    LEFT JOIN policies p
        ON c.IDpol = p.IDpol
    GROUP BY c.IDpol, c.ClaimAmount, policy_match
    HAVING COUNT(*) > 1
)
SELECT
    COUNT(*) AS unmatched_repeated_combinations
FROM repeated_claims
WHERE policy_match = 'Unmatched';


/*
Results:
- table above lists repeated comb. of policy ID and 
claim amount, distinguishing between matched
and unmatched policy IDs

-the separate count shows repeated ID/amount comb. among
unmatched claims --> not the total number of unmatched
claim records(195)

Interpretation:
These repeated combinations may indicate potential duplicates,
but this cannot be confirmed because the dataset contains
no unique claim identifier.
*/


--------------------------------------------------------------------------
--1.6 Check claim amounts for missing/invalid values

SELECT
    COUNT(*) AS total_claim_records,
    SUM(CASE WHEN IDpol IS NULL THEN 1 ELSE 0 END) AS missing_policy_id,
    SUM(CASE WHEN ClaimAmount IS NULL THEN 1 ELSE 0 END) AS missing_claim_amount,
    SUM(CASE WHEN ClaimAmount = 0 THEN 1 ELSE 0 END) AS zero_claim_amount,
    SUM(CASE WHEN ClaimAmount < 0 THEN 1 ELSE 0 END) AS negative_claim_amount,
    MIN(ClaimAmount) AS minimum_claim_amount,
    MAX(ClaimAmount) AS maximum_claim_amount
FROM claims;

-- no missing IDpol, no missing claim amount,
-- all claim amounts are strictly positive
-- min = 1.0 ; max = 4075400.56


---------------------------------------------------------------------------
--1.7 inspect large values and checking whether claims 
--match a policy

SELECT
    IDpol,
    ClaimAmount
FROM claims
ORDER BY ClaimAmount DESC
LIMIT 10;

SELECT
    c.IDpol,
    c.ClaimAmount,
    CASE
        WHEN p.IDpol IS NULL THEN 'Unmatched'
        ELSE 'Matched'
    END AS policy_match
FROM claims c
LEFT JOIN policies p
    ON c.IDpol = p.IDpol
ORDER BY c.ClaimAmount DESC
LIMIT 10;

/*
Remark:

The 10 largest claim amounts are matched to policy IDs.

Checking for a plausible amount is still an open problem
*/

---------------------------------------------------------------
--1.8 Compute statistical variables and examining the
--distribution of unmatched claims across policy IDs

SELECT
    COUNT(*) AS unmatched_claims,
    MIN(c.ClaimAmount) AS minimum_claim_amount,
    AVG(c.ClaimAmount) AS average_claim_amount,
    MAX(c.ClaimAmount) AS maximum_claim_amount,
    SUM(c.ClaimAmount) AS total_unmatched_claim_amount
FROM claims c
LEFT JOIN policies p
    ON c.IDpol = p.IDpol
WHERE p.IDpol IS NULL;

--count unmatched claim records and distinct policy IDs
-- to assess whether the 195 records are concentrated
-- in a few IDs or spread across multiple IDs

SELECT
    COUNT(*) AS unmatched_claim_records,
    COUNT(DISTINCT c.IDpol) AS distinct_unmatched_policy_ids
FROM claims c
LEFT JOIN policies p
    ON c.IDpol = p.IDpol
WHERE p.IDpol IS NULL;


/*
Result:

The 195 unmatched claim records are associated with
6 distinct policy IDs.
*/



--The following query examines these IDs and their claim amounts.

SELECT
    c.IDpol,
    COUNT(*) AS claim_records,
    MIN(c.ClaimAmount) AS minimum_claim_amount,
    ROUND(AVG(c.ClaimAmount), 2) AS average_claim_amount,
    MAX(c.ClaimAmount) AS maximum_claim_amount,
    ROUND(SUM(c.ClaimAmount), 2) AS total_claim_amount
FROM claims c
LEFT JOIN policies p
    ON c.IDpol = p.IDpol
WHERE p.IDpol IS NULL
GROUP BY c.IDpol
ORDER BY claim_records DESC;



----------------------------------------------------------------------------

/*
Important Remark:

The 195 claim records without a matching policy ID are a known
inconsistency in the freMTPL2 dataset, intentionally retained
according to the README.

The README also reports discrepancies between ClaimNb and claim
amounts for 9,117 policies.

With 195 out of 26,639 claim records (~0.73%), the unmatched
share is relatively small. These records are excluded when
claim data is joined with policy attributes.

However, their exclusion could potentially introduce bias into
the claim severity distribution and should be kept in mind
when interpreting the severity analysis.
*/

----------------------------------------------------------------------------

