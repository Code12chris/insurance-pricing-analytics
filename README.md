# About
This project was developed independently as part of self-directed study in actuarial science and insurance mathematics, following the completion of an M.Sc. in Mathematics.

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


## Project Structure

```text
insurance-pricing-analytics/
│
├── main.py              # Complete analysis workflow
├── queries.sql          # SQL queries used for portfolio exploration
├── insurance.db         # SQLite database created from the CSV files
├── analyse_plots.pdf    # important plots from various analytic sections
├── freMTPL2freq.csv     # Policy and frequency dataset
├── freMTPL2sev.csv      # Claim severity dataset
├── README_DE.md         # deutsche Version Projektübersicht
└── README.md            # project overview
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
* Mean claim amount around €2,279.
* Maximum claim amount around €4 million.
* Extreme claims are retained in the analysis.

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

   WMRAE (Age Groups)	         1.13%
   WMRAE (Bonus-Malus Groups)	   3.06%
   Deviance	                     1.65
   Pearson Chi²                  46.99   
```

The Gamma GLM shows very good calibration for the average claim severity across tariff groups, while Pearson dispersion indicates remaining heavy-tail variability that is not fully explained by the Gamma distribution.


## Tariff Relativities

Severity rating factors are obtained by exponentiating the Gamma GLM coefficients.

# Age Groups

```text
   Age Group            Relative Severity

   18-25                1.000
   26-40                0.474
   41-60                0.408
   61+                  0.513
```

The youngest driver group is estimated to have the highest expected claim severity.


# Bonus-Malus Groups

```text
   Bonus-Malus Group            Relative Severity

   <=50                         1.000
   51-64                        1.023
   65-80                        0.972
   81-100                       1.243
   101-125                      0.758
   >125                         1.091
```

Bonus-Malus effects are included for comparison but are not statistically significant in the selected Gamma severity model.


## Pure Premium Calculation

The final pricing component is the **Pure Premium**, which combines the expected claim frequency and the expected claim severity into a single expected annual claim cost.

**Pure Premium = Expected Claim Frequency × Expected Claim Severity**

The frequency predictions are obtained from the Poisson GLM, estimated with a log link and `log(Exposure)` as an offset. Consequently, the predicted claim frequencies (`freq_pred`) account for differences in policy exposure.

The expected claim severity is obtained from the selected Gamma GLM. Multiplying both model predictions yields the expected annual claim cost for each tariff class.

## Pricing Results

The Pure Premium analysis combines the estimated frequency and severity models for all combinations of driver age group and Bonus-Malus group.

The resulting tariff matrix contains **24 tariff classes** and illustrates how expected annual claim costs vary across different risk profiles.

### Main findings

- **Lowest Pure Premium:** Driver age **26–40** with **Bonus-Malus ≤50** → **€121.63**
- Driver age **41–60** with **Bonus-Malus ≤50** → **€150.88**
- **Highest Pure Premium:** Driver age **18–25** with **Bonus-Malus >125** → **€2,065.53**

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
| Observed portfolio claim cost | **€169.31** |
| Modeled portfolio Pure Premium | **€223.34** |
| Portfolio relative error | **31.91%** |

The modeled portfolio Pure Premium overestimates the observed claim cost by approximately **31.9%** on portfolio level. This metric evaluates the calibration of the overall pricing model across the complete insurance portfolio.

### Tariff-Class Validation

As an additional plausibility check, modeled and observed Pure Premium values were compared separately for the **24 tariff classes**.

| Metric | Result |
|--------|-------:|
| Exposure-weighted tariff-class relative error | **49.80%** |

This tariff-class metric should **not** be interpreted as the overall model error. Individual tariff classes contain substantially different exposure volumes and are affected by a small number of very large claims. As a result, tariff-class errors are considerably more volatile than the aggregated portfolio validation.

## Interpretation of Results

The pricing workflow produces meaningful differences between driver risk profiles while also illustrating the limitations of a simplified actuarial pricing model.

### Frequency Model

The Poisson GLM identifies Bonus-Malus as the dominant driver of claim frequency. Higher Bonus-Malus groups consistently receive substantially higher expected claim frequencies.

### Severity Model

The Gamma GLM captures systematic differences in average claim severity across age groups. Bonus-Malus effects in the severity model are comparatively small and are not statistically significant.

### Combined Pricing Model

The resulting Pure Premium reflects both components simultaneously. High-risk tariff classes receive significantly higher expected annual claim costs than low-risk tariff classes, which is consistent with the underlying frequency and severity estimates.

At the same time, the portfolio validation indicates that the simplified model still overestimates observed portfolio claim costs. This demonstrates that the model captures important pricing patterns but does not fully explain the variability of the underlying insurance portfolio.

## Limitations

This project intentionally implements a simplified actuarial pricing workflow and therefore has several limitations.

- Only **driver age** and **Bonus-Malus group** are used as rating variables.
- Additional pricing factors such as vehicle characteristics, geographic information, fuel type, or vehicle power are not included.
- The severity distribution remains strongly right-skewed with a small number of extremely large claims.
- The Gamma GLM captures average claim severity well but cannot fully explain heavy-tail variability in individual claims.
- Portfolio validation shows that the modeled Pure Premium remains above the observed portfolio claim cost, indicating remaining calibration error.

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
* [ ] Determine exposure influence in individual tariff classes *(in progress)*.
* [ ] Pure Premium validation (deviation analysis) *(in progress)*.
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
Python 3.8.5 or higher is required.

### Installation

1. Clone the repository:

   git clone https://github.com/Code12chris/insurance-pricing-analytics.git

   cd insurance-pricing-analytics


2. Create and activate a virtual environment:
   python -m venv venv

   Windows:   venv\Scripts\activate
   Mac/Linux: source venv/bin/activate


3. Install dependencies:
   pip install pandas numpy scipy matplotlib statsmodels seaborn


4. Run the analysis:
   python main.py



### Notes
- The SQLite database (insurance.db) is created automatically on first run.
- All relevant plots are exported as a PDF file.
- No additional configuration required.

