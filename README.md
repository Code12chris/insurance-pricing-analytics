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
* SQLite
* Statsmodels
* Matplotlib
* VS Code

## Dataset

The project uses the publicly available **French Motor Third-Party Liability (freMTPL2)** dataset.

* `freMTPL2freq.csv` – policy information, exposure, and claim counts.
* `freMTPL2sev.csv` – individual claim amounts.

Both datasets are merged using the policy identifier (`IDpol`).


## Project Structure

insurance-pricing-analytics/
│
├── main.py              # Complete analysis workflow
├── queries.sql          # SQL queries used for portfolio exploration
├── insurance.db         # SQLite database created from the CSV files
├── freMTPL2freq.csv     # Policy and frequency dataset
├── freMTPL2sev.csv      # Claim severity dataset
└── README.md



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

   Metric                        Result

   WMRAE (Age Groups)	         1.13%
   WMRAE (Bonus-Malus Groups)	   3.06%
   Deviance	                     1.65
   Pearson Chi²                  46.9   

The Gamma GLM shows very good calibration for the average claim severity across tariff groups, while Pearson dispersion indicates remaining heavy-tail variability that is not fully explained by the Gamma distribution.


### Tariff Relativities

Severity rating factors are obtained by exponentiating the Gamma GLM coefficients.

# Age Groups

   Age Group            Relative Severity

   18-25                1.000
   26-40                0.474
   41-60                0.408
   61+                  0.513

The youngest driver group is estimated to have the highest expected claim severity.


# Bonus-Malus Groups

   Bonus-Malus Group            Relative Severity

   <=50                         1.000
   51-64                        1.023
   65-80                        0.972
   81-100                       1.243
   101-125                      0.758
   >125                         1.091

Bonus-Malus effects are included for comparison but are not statistically significant in the selected Gamma severity model.



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
* [ ] Pure Premium calculation *(in progress)*.
* [ ] Portfolio procing examples and visualization *(in progress)*.



## Key Learning Outcomes

This project demonstrates practical implementation of actuarial pricing methods in Python, including:

* insurance data preparation with SQL and Pandas
* Poisson GLMs for claim frequency
* Gamma GLMs for claim severity
* comparison of alternative severity distributions
* actuarial model validation using tariff-group calibration and WMRAE
* interpretation of GLM coefficients as multiplicative rating factors


## Planned Improvements

The current repository contains the complete implementation in main.py, where the full actuarial workflow is developed and executed.

A second version of the project is planned as a Jupyter Notebook after the analysis is completed. The notebook will present the finished workflow in a structured, stakeholder-friendly format by combining code, visualizations, mathematical explanations, and model interpretations in a single document.

This separation keeps the repository organized: the Python script serves as the development version, while the notebook will serve as the presentation and documentation version of the completed project.



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
