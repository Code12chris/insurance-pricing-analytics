[🇬🇧 English](README.md) | [🇩🇪 Deutsch](README_DE.md)

# About
This project was developed independently as part of self-directed study in actuarial science and insurance mathematics, following the completion of an M.Sc. in Mathematics.

*Transparency note:* The analysis was built by myself. For a later review of the code and results I used an AI assistant (Claude); every finding from that review was verified against the data, and all modelling decisions are my own.

# Insurance Pricing Analytics – Frequency and Severity Modeling with Python

A portfolio project implementing a simplified actuarial pricing workflow for motor insurance using Python, SQL, and statistical modeling. The project follows a standard actuarial approach by modeling claim frequency and claim severity separately and validating alternative severity models.

## Project Overview

This project reproduces the core steps of an actuarial pricing analysis:

* Data preparation using Pandas and SQLite.
* Exploratory analysis of insurance portfolios and claims.
* Claim frequency modeling with a Poisson GLM.
* Claim severity modeling with Gamma and Lognormal models.
* Statistical model validation and comparison.
* Preparation of actuarial rating factors for insurance pricing.

The project follows the common actuarial separation into **Frequency** (how often claims occur) and **Severity** (how large claims are).


## Technologies

* Python
* Pandas
* NumPy
* SciPy
* SQLite
* Statsmodels
* Matplotlib
* Seaborn
* VS Code


## Dataset

The project uses the publicly available **French Motor Third-Party Liability (freMTPL2)** dataset.

* `freMTPL2freq.csv` – policy information, exposure, and claim counts.
* `freMTPL2freq.csv` – with 678013 rows and 12 columns
* `freMTPL2sev.csv` – individual claim amounts.
* `freMTPL2sev.csv` – with 26639 rows and 2 columns


Both datasets are merged using the policy identifier (`IDpol`).

### Data consistency and cleaning

Claim counts (`ClaimNb`) and claim amounts must describe the same claims, otherwise *frequency × severity* cannot be compared with observed claim costs. A consistency check shows that they do not match in the raw data:

| Check | Result |
|-------|-------:|
| Sum of `ClaimNb` | 36,102 |
| Rows in `freMTPL2sev` | 26,639 (ratio 1.355) |
| Claims without a matching policy | 195 |

The missing claim amounts are **not** spread randomly. Almost all of them sit in one block at the start of the dataset:

| | Block `IDpol < 24,952` | Rest of portfolio |
|---|---:|---:|
| Policies | 9,387 (every policy has ≥ 1 claim) | 668,626 |
| Share of exposure | 1.3% | 98.7% |
| Share of all `ClaimNb` | 27.5% | 72.5% |
| Claims with a recorded amount | 3% | 99.9% |
| Annual claim frequency | 2.07 | 0.074 |

Cleaning steps:

The 195 claims without a matching policy belong to only **6 policy numbers with 21 to 66 claims each** (claim-bearing policies normally have 1.06 claims). The neighbouring policy numbers exist in the policy table, so these are gaps in the policy data. All six lie in the range 2,220,000–2,287,000, which also contains 5 of the 8 policies with 5–16 claims (see step 3). This points to fleets or group contracts that are not represented as individual risks.

1. Remove the whole block (entire policies). Removing only claim-bearing policies without amounts would bias the frequency downwards, because their claim-free counterparts would remain.
2. Remove the remaining policies whose `ClaimNb` differs from the number of recorded claim amounts.
3. Remove policies with more than 4 claims (8 policies with 5 to 16 claims, most of them within 0.07–0.41 policy years and with near-identical driver profiles; likely fleet or recording errors). Removing instead of capping keeps counts and amounts consistent.
4. Cap exposure at 1 year (1,224 policies).
5. Remove claims without a policy and claims of removed policies.

After cleaning: **668,595 policies, 353,540 policy years, 26,065 claims, each with exactly one claim amount** (1.4% of policies and 2.6% of the total claim amount removed). The block also distorted the tariff structure: it over-represents Bonus-Malus ≤50 and drivers aged 61+, so cleaning makes the Bonus-Malus relativities clearly steeper (e.g. BM >125: 6.2 → 9.7).


## Project Structure

```text
insurance-pricing-analytics/
│
├── main.py               # Complete analysis workflow
├── data_prep.py          # data loading, consistency checks and cleaning
├── validation.py         # out-of-sample validation, overdispersion, large losses
├── requirements.txt      # Python dependencies
├── queries.sql           # SQL queries used for portfolio exploration
├── policies_analysis.sql # SQL queries used for a more detailed portfolio analysis
├── insurance.db          # SQLite database created from the CSV files (generated)
├── analyse_plots.pdf     # important plots from various analytic sections
├── validation_plots.pdf  # plots from validation.py
├── data/
│   ├── freMTPL2freq.csv  # Policy and frequency dataset
│   └── freMTPL2sev.csv   # Claim severity dataset
├── README_DE.md          # deutsche Version Projektübersicht
└── README.md             # project overview
```


## Frequency Modeling

Claim frequency is modeled with a **Poisson Generalized Linear Model (GLM)** using a log link and policy exposure as an offset.

### Rating variables

* Driver age groups
* Bonus-Malus groups

The model estimates the expected number of claims per policy and provides multiplicative tariff effects for the frequency component of pricing.

## Severity Modeling

The severity analysis considers only positive claim amounts.

### Exploratory analysis

The claim amount distribution shows typical heavy-tail insurance characteristics:

* Strong right-skewed distribution.
* Many small claims and a few extremely large claims.
* Median claim amount around €1,172.
* Mean claim amount around €2,267 (after cleaning).
* Maximum claim amount around €4 million.
* Extreme claims are retained in the analysis.
* All three claims above €1 million belong to drivers aged 18–20 with Bonus-Malus 100. Without them, the mean claim amount of the age group 18–25 would be about €2,300 instead of €5,140.

Severity is analyzed across driver age groups and Bonus-Malus groups.

### Gamma GLM (Selected Model)

A Gamma GLM with a log link is used as the baseline severity model.


### Model
ClaimAmount ~ age_group + bm_group

### Main findings:

Driver age has a statistically significant impact on claim severity.
Bonus-Malus is not statistically significant in the Gamma severity model.
The Gamma GLM reproduces observed mean claim severities across tariff groups accurately.


### Lognormal Model (Benchmark)

A Lognormal model is estimated by regressing the logarithm of claim amounts.

The analysis includes:

* coefficient interpretation
* multiplicative severity factors
* residual diagnostics
* Q-Q plots
* prediction comparison on the euro scale with the Gamma GLM

The Gamma GLM outperforms the Lognormal model on the original claim amount scale and is selected as the final severity model.


### Model Validation

Model validation is performed on tariff-group level.


### Gamma GLM Calibration

Observed and predicted mean claim severities are compared across:

* driver age groups
* Bonus-Malus groups


### Validation metrics

* Relative prediction error by tariff group.
* Weighted Mean Relative Absolute Error (WMRAE).
* Deviance / residual degrees of freedom.
* Pearson Chi² / residual degrees of freedom.

### Validation Results

```text
   Metric                        Result

   WMRAE (Age Groups)            1.14%
   WMRAE (Bonus-Malus Groups)    3.11%
   Deviance / df                 1.64
   Pearson Chi² / df            47.34
```

The WMRAE values are in-sample: they are computed on the same groups that enter the model as rating factors, so they mainly show calibration, not predictive power.

For a Gamma GLM, Deviance/df and Pearson Chi²/df are not goodness-of-fit measures to be compared with 1. They are estimators of the dispersion parameter φ (Var = φ·μ²). Pearson/df ≈ 47 implies a coefficient of variation of about √47 ≈ 6.9, which reflects the heavy tail of the claim distribution.


## Tariff Relativities

Severity rating factors are obtained by exponentiating the Gamma GLM coefficients.

# Age Groups

```text
   Age Group            Relative Severity

   18-25                1.000
   26-40                0.473
   41-60                0.405
   61+                  0.514
```

The youngest driver group is estimated to have the highest expected claim severity. This effect is driven largely by the three claims above €1 million in this group, so it should be treated with caution (large-loss treatment is a planned next step).


# Bonus-Malus Groups

```text
   Bonus-Malus Group            Relative Severity

   <=50                         1.000
   51-64                        1.030
   65-80                        0.976
   81-100                       1.248
   101-125                      0.761
   >125                         1.094
```

Bonus-Malus effects are included for comparison but are not statistically significant in the selected Gamma severity model.


## Pure Premium Calculation

The final pricing component is the **Pure Premium**, which combines the expected claim frequency and the expected claim severity into a single expected annual claim cost.

**Pure Premium = Expected Claim Frequency × Expected Claim Severity**

The frequency predictions are obtained from the Poisson GLM, estimated with a log link and `log(Exposure)` as an offset. Predictions are made for one policy year (exposure = 1), so `freq_pred` is an annual claim frequency. Exposure enters again when aggregating to portfolio level (exposure-weighted average).

The expected claim severity is obtained from the selected Gamma GLM. Multiplying both model predictions yields the expected annual claim cost for each tariff class.

## Pricing Results

The Pure Premium analysis combines the estimated frequency and severity models for all combinations of driver age group and Bonus-Malus group.

The resulting tariff matrix contains **24 tariff classes** and illustrates how expected annual claim costs vary across different risk profiles.

### Main findings

- **Lowest Pure Premium:** Driver age **26–40** with **Bonus-Malus ≤50** → **€76.84**
- Driver age **41–60** with **Bonus-Malus ≤50** → **€98.04**
- **Highest Pure Premium:** Driver age **18–25** with **Bonus-Malus >125** → **€2,109.01**

The pricing results show a clear increase in expected claim costs for higher Bonus-Malus groups. Driver age affects both claim frequency and claim severity, while the Bonus-Malus effect is primarily driven by the frequency model.

## Pure Premium Tariff Matrix

The complete tariff matrix is visualized as a heatmap covering all 24 combinations of driver age groups and Bonus-Malus groups.

The visualization highlights the combined effect of both pricing components and makes the differences between low-risk and high-risk tariff classes immediately visible.

![Pure Premium Heatmap](pure_premium_heatmap.png)

The heatmap shows that the highest expected annual claim costs occur for young drivers with high Bonus-Malus levels, whereas the lowest expected costs occur for middle-aged drivers with low Bonus-Malus levels.

## Model Validation

After estimating the pricing models, the modeled Pure Premium was compared with the observed portfolio claim costs.

### Portfolio Validation

The observed portfolio claim cost per unit of exposure is compared with the exposure-weighted modeled Pure Premium.

| Metric | Result |
|--------|-------:|
| Observed portfolio claim cost | **€167.15** |
| Modeled portfolio Pure Premium | **€165.82** |
| Portfolio relative error | **−0.79%** |

**Before data cleaning, the model overestimated the observed claim cost by +31.9%.** The cause was not the model or the exposure but the data: the frequency model learned from all `ClaimNb`, while observed costs only contained claims with a recorded amount. The overestimation therefore matched the ratio of claim counts to recorded claim amounts (≈ 1.35).

The remaining −0.79% is **not** evidence of predictive quality. A Poisson GLM with log link reproduces the total claim count exactly in-sample, and the Gamma GLM reproduces the total claim amount almost exactly. The metric only confirms that frequency and severity data are now consistent. Out-of-sample validation (train/test split) is the next step.

### Tariff-Class Validation

As an additional plausibility check, modeled and observed Pure Premium values were compared separately for the **24 tariff classes**.

| Metric | Result |
|--------|-------:|
| Exposure-weighted tariff-class relative error | **11.61%** (49.80% before cleaning) |

This tariff-class metric should **not** be interpreted as the overall model error. Individual tariff classes contain substantially different exposure volumes and are affected by a small number of very large claims. As a result, tariff-class errors are considerably more volatile than the aggregated portfolio validation.

## Interpretation of Results

The pricing workflow produces meaningful differences between driver risk profiles while also illustrating the limitations of a simplified actuarial pricing model.

### Frequency Model

The Poisson GLM identifies Bonus-Malus as the dominant driver of claim frequency. Higher Bonus-Malus groups consistently receive substantially higher expected claim frequencies.

### Severity Model

The Gamma GLM captures systematic differences in average claim severity across age groups. Bonus-Malus effects in the severity model are comparatively small and are not statistically significant.

### Combined Pricing Model

The resulting Pure Premium reflects both components simultaneously. High-risk tariff classes receive significantly higher expected annual claim costs than low-risk tariff classes, which is consistent with the underlying frequency and severity estimates.

At the same time, individual tariff classes deviate considerably from their observed claim costs, mainly in small classes and in the age group 18–25, where three very large claims dominate the observed values.

## Limitations

This project intentionally implements a simplified actuarial pricing workflow and therefore has several limitations.

- Only **driver age** and **Bonus-Malus group** are used as rating variables.
- Additional pricing factors such as vehicle characteristics, geographic information, fuel type, or vehicle power are not included.
- The severity distribution remains strongly right-skewed with a small number of extremely large claims.
- The Gamma GLM captures average claim severity well but cannot fully explain heavy-tail variability in individual claims.
- All validation so far is in-sample; out-of-sample validation is still missing.
- The severity effect of young drivers depends heavily on three claims above €1 million; large losses are not yet treated separately.
- The cause of the inconsistent data block at the start of the dataset cannot be determined from the data; the block is excluded and documented.

These limitations are expected for a compact GLM pricing model and provide opportunities for further model refinement rather than indicating a failure of the pricing approach.


## Project Status

* [x] SQLite database creation and SQL portfolio exploration.
* [x] Exploratory frequency analysis.
* [x] Poisson GLM for claim frequency.
* [x] Exploratory severity analysis.
* [x] Gamma GLM estimation.
* [x] Lognormal benchmark model.
* [x] Gamma vs. Lognormal model comparison.
* [x] Residual diagnostics.
* [x] Gamma model validation (WMRAE, Deviance, Pearson Chi²).
* [x] Severity tariff relativities.
* [x] Pure Premium calculation.
* [x] Visualization tariff classes.
* [x] Data consistency check and cleaning (cause of the former +31.9% portfolio deviation).
* [x] Pure Premium portfolio validation (in-sample).
* [ ] Out-of-sample validation (train/test split, deviance, lift chart / Gini) *(in progress)*.
* [ ] Overdispersion check (Negative Binomial / Quasi-Poisson) and large-loss treatment *(in progress)*.
* [ ] Additional rating variables *(planned)*.
* [ ] Finalizing project and developing jupyter-presentation *(in progress)*.



## Key Learning Outcomes

This project demonstrates practical implementation of actuarial pricing methods in Python, including:

* insurance data preparation with SQL and Pandas
* Poisson GLMs for claim frequency
* Gamma GLMs for claim severity
* comparison of alternative severity distributions
* actuarial model validation using tariff-group calibration and WMRAE
* interpretation of GLM coefficients as multiplicative rating factors


## Planned Improvements

The current repository contains the complete implementation in `main.py`, where the pricing workflow is developed and validated.

Planned extensions include:

- Creating a structured Jupyter Notebook version of the project for presentation and documentation.
- Extending the pricing model with additional rating variables available in the dataset.
- Investigating calibration improvements for the Pure Premium model across tariff classes.
- Exploring alternative severity distributions and additional validation metrics.


### Future Work

The public `freMTPL2` dataset does not contain claim development information required for reserving methods or company-specific data required for Solvency II capital modeling.

These topics are therefore outside the scope of this project but represent natural extensions when more comprehensive insurance datasets are available.


## How to Run

### Requirements
Python 3.11 or higher (pandas 3 requires it). Tested with:

| Package | Tested version |
|---|---|
| Python | 3.13.17 |
| pandas | 3.1.1 |
| numpy | 2.5.5 |
| statsmodels | 0.15.0 |
| scipy | 1.18.1 |
| matplotlib | 3.11.2 |
| seaborn | 0.13.2 |

### Installation

1. Clone the repository:

   git clone https://github.com/Code12chris/insurance-pricing-analytics.git

   cd insurance-pricing-analytics


2. Create and activate a virtual environment:
   python -m venv .venv

   Windows (PowerShell): .venv\Scripts\activate
   Windows (Git Bash):   source .venv/Scripts/activate
   Mac/Linux:            source .venv/bin/activate


3. Install dependencies:
   pip install -r requirements.txt


4. Run the analysis:
   python main.py
   python validation.py



### Notes
- The SQLite database (insurance.db) is created automatically on first run.
- All relevant plots are exported as PDF files (`analyse_plots.pdf`, `validation_plots.pdf`).
- Run the scripts from the project folder; data paths are relative (`data/`).
- No additional configuration required.

