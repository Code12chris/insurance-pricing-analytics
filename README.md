# About
This project was developed independently as part of self-directed study in actuarial science and insurance mathematics, following the completion of an M.Sc. in Mathematics.

# Insurance Pricing Analytics – Frequency and Severity Modeling with Python

A portfolio project implementing a simplified actuarial pricing workflow for motor insurance using Python, SQL, and statistical modeling. The project analyzes insurance claim frequency and claim severity separately and compares alternative severity models using real insurance portfolio data.

## Project Overview

This project reproduces the core steps of an actuarial pricing analysis:

* Prepare insurance policy and claim data.
* Build a SQLite database for portfolio analysis.
* Explore claim frequency and claim severity.
* Estimate actuarial pricing models.
* Evaluate model assumptions with residual diagnostics and visualizations.

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

The severity data is provided under data/freMTPL2sev.csv 
The frequency data exceeds upload limit of 25 MB. A link to the `freMTPL2freq.csv` file will
be given in the future.

## Project Structure

```text id="bjlnsj"
insurance-pricing-analytics/
│
├── main.py              # Complete analysis workflow
├── queries.sql          # SQL queries used for portfolio exploration
├── insurance.db         # SQLite database created from the CSV files
├── freMTPL2freq.csv     # Policy and frequency dataset
├── freMTPL2sev.csv      # Claim severity dataset
└── README.md
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

The claim amount distribution shows typical insurance characteristics:

* Strong right skew.
* Many small claims and a few extremely large claims.
* Median claim amount around €1,172.
* Maximum claim amount above €4 million.
* Extreme claims are retained in the analysis.

Severity is analyzed across driver age groups and Bonus-Malus groups.

### Gamma GLM

A Gamma GLM with a log link is used as the baseline severity model.

Main findings include:

* Significant age effects.
* Limited explanatory power of Bonus-Malus.
* Evidence of overdispersion caused by heavy-tail claims.

### Lognormal Model

As an alternative, the logarithm of claim amounts is modeled with linear regression.

The analysis includes:

* estimation of multiplicative severity factors,
* confidence intervals,
* residual diagnostics,
* Q-Q plots,
* comparison with the Gamma GLM.

## Model Diagnostics

Model assumptions are evaluated using:

* Residual vs fitted plots.
* Residual histograms.
* Q-Q plots.
* Scale-location plots.
* Comparison of observed and predicted claim severity across tariff groups.

These diagnostics are used to compare the Gamma and Lognormal approaches for insurance claim severity modeling.

## Key Learning Outcomes

This project demonstrates practical implementation of actuarial pricing methods in Python, including:

* SQL-based insurance data preparation.
* Exploratory insurance portfolio analysis.
* Poisson GLM for claim frequency.
* Gamma and Lognormal severity modeling.
* Interpretation of multiplicative tariff effects.
* Statistical model diagnostics and comparison.

## Project Status

* [x] Data preparation and SQLite database.
* [x] Exploratory frequency analysis.
* [x] Poisson GLM frequency model.
* [x] Exploratory severity analysis.
* [x] Gamma GLM severity model.
* [x] Lognormal severity model.
* [ ] Residual diagnostics and model comparison *(in progress)*.
* [ ] Final actuarial model evaluation *(in progress)*.


## How to Run

### Requirements
Python 3.8.5 or higher is required.

### Installation

1. Clone the repository:
   git clone https://github.com/YourUsername/insurance-pricing-analytics.git cd insurance-pricing-analytics

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
- All plots are exported as a PDF file.
- No additional configuration required.
