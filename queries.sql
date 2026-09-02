
/*
Diese Datei zeigt die Datenaufbereitung und
erste Analyse mit SQL. Die erzeugten Tabellen
wurden hier gezeigt, koennen aber auch per
python-datei aufgerufen und ausgefuehrt werden
*/


--Tabellen policies und claims zum anschauen

SELECT *
FROM policies
LIMIT 5;

/*
Zeigt die Spalten und danach Zeilen an

SELECT COUNT(*) AS rows_policies
FROM policies;

SELECT COUNT(*) AS columns_policies
FROM pragma_table_info('policies');

policies hat 678013 Zeilen und 12 Spalten
*/


SELECT *
FROM claims
LIMIT 5;

/*
Zeigt die Spalten und danach Zeilen an

SELECT COUNT(*) AS rows_claims
FROM claims;

SELECT COUNT(*) AS columns_claims
FROM pragma_table_info('claims');

claims hat 26639 Zeilen und 2 Spalten
*/

----------------------------------------------------------

--Schadenfrequenz bestimmen
SELECT
    SUM(ClaimNb) * 1.0 / SUM(Exposure) AS claim_frequency
FROM policies;


------------------------------------------------------

--Schadenhöhe bestimmen

SELECT
    COUNT(*) AS number_of_claims,
    AVG(ClaimAmount) AS average_claim_amount,
    MAX(ClaimAmount) AS largest_claim
FROM claims;


------------------------------------------------------

--durschnittliche Schadenhöhe

SELECT
AVG(ClaimAmount) AS average_claim_amount
FROM claims;


------------------------------------------------------

--Vertrag und Schaden verbinden
SELECT
    p.IDpol,
    p.Exposure,
    p.ClaimNb,
    c.ClaimAmount
FROM policies p
JOIN claims c
    ON p.IDpol = c.IDpol
LIMIT 5;


------------------------------------------------------

--Schadenfrequenz nach Fahreralter
SELECT
    CASE
        WHEN DrivAge < 25 THEN 'u25'
        WHEN DrivAge < 40 THEN '25-39'
        WHEN DrivAge < 60 THEN '40-59'
        ELSE '60+'
    END AS age_group,
    SUM(ClaimNb)*1.0 / SUM(Exposure) AS claim_frequency
FROM policies
GROUP BY age_group
ORDER BY
    CASE
        WHEN age_group = 'u25' THEN 1
        WHEN age_group = '25-39' THEN 2
        WHEN age_group = '40-59' THEN 3
        ELSE 4
    END;


------------------------------------------------------

-- Erwartete Schadenbelastung (Pure Premium) nach Altersgruppe
-- WITH clause auf geeksforgeeks nachlesbar, mehrere
-- argumente auf dba stack exchange mult table in WITH statement
WITH freq AS (
SELECT
--temporaere zwischentabelle freq fuer Schadenfreq
    CASE
        WHEN DrivAge < 25 THEN 'u25'
        WHEN DrivAge < 40 THEN '25-39'
        WHEN DrivAge < 60 THEN '40-59'
        ELSE '60+'
        END AS age_group,
        SUM(ClaimNb)*1.0 / SUM(Exposure) AS claim_frequency
FROM policies
GROUP BY age_group
--berechnete schadenfrequenz getrennt nach altersgruppen
),
sev AS (
SELECT
--temporaere zwischentabelle sev-(erity) fuer Schadenhoehe
    CASE
        WHEN p.DrivAge < 25 THEN 'u25'
        WHEN p.DrivAge < 40 THEN '25-39'
        WHEN p.DrivAge < 60 THEN '40-59'
        ELSE '60+'
    END AS age_group,
--berechnet durchsch Schadenhoehe
    AVG(c.ClaimAmount) AS average_claim_amount
FROM policies p
JOIN claims c ON p.IDpol = c.IDpol
GROUP BY age_group
)
SELECT
/*
erstellt tabelle mit altersgruppe, schadenfrequenz,
durchschn Schaden und pure premium = freq x Schadenhoehe
*/
    freq.age_group,
    ROUND(freq.claim_frequency, 4) AS claim_frequency,
    ROUND(sev.average_claim_amount, 2) AS average_claim_amount,
    ROUND(freq.claim_frequency * sev.average_claim_amount, 2) AS pure_premium
FROM freq
JOIN sev ON freq.age_group = sev.age_group
--verbinden beide temp tabelle ueber altersgruppen
ORDER BY
    CASE
        When freq.age_group = 'u25' THEN 1
        When freq.age_group = '25-39' THEN 2
        When freq.age_group = '40-59' THEN 3
        ELSE 4
    
    END;

--damit pure premium nach alter durch temp tabellen bestimmt

-------------------------------------------------------------
--jetzt bonus maulaus berechnen

--zeigt Aenderung von Schadenfreq mit B-Malus-Klasse

SELECT
    BonusMalus,
    ROUND(SUM(ClaimNb) * 1.0 / SUM(Exposure), 4) AS claim_frequency
FROM policies
GROUP BY BonusMalus
ORDER BY BonusMalus;


/*
gibt an wieviele bonus-malus-werte da sind
min = 50; max=230; verschiedene = 115

SELECT 
    MIN(BonusMalus) AS min_bonusmalus,
    MAX(BonusMalus) AS max_bonusmalus,
    COUNT(DISTINCT BonusMalus) AS number_of_classes
FROM policies;
*/

