"""Insurance Pricing Analytics: base tariff for French motor liability (freMTPL2).

Run:  python main.py
Output: console tables, analyse_plots.pdf, figures/pure_premium_heatmap.png,
        insurance.db (raw tables for policies_analysis.sql)

Workflow (one module per step):
  1. data_prep   load the CSV files, store them in SQLite, check consistency, clean
  2. eda         claim frequency and claim severity, one-way by age and Bonus-Malus
  3. frequency   Poisson GLM with exposure offset
  4. severity    Gamma GLM vs. lognormal model
  5. pricing     pure premium per tariff cell and validation against observed costs

Further steps in separate scripts:
  validation.py         out-of-sample validation, overdispersion, large losses
  features.py           additional rating factors, credibility, tariff tables
  policies_analysis.sql the same data quality checks and analyses in SQL
"""
import matplotlib

matplotlib.use("Agg")                     # write plots to file, no windows

from data_prep import (load_raw, write_sqlite, consistency_report, clean,
                       add_tariff_groups)
from metrics import print_section, pdf_pages
import eda
import frequency
import severity
import pricing


def main():
    # 1. data -----------------------------------------------------------------
    print_section("Data: load, store in SQLite, check consistency, clean")
    policies_raw, claims_raw = write_sqlite(*load_raw())
    consistency_report(policies_raw, claims_raw)
    policies, claims = clean(policies_raw, claims_raw)
    policies = add_tariff_groups(policies)
    # claims with the rating factors of their policy (every claim has a policy)
    claims_rated = claims.merge(policies[["IDpol", "age_group", "bm_group"]], on="IDpol")

    with pdf_pages("analyse_plots.pdf") as pdf:
        # 2. exploratory analysis ---------------------------------------------
        portfolio_frequency = eda.frequency_overview(policies, pdf)
        eda.frequency_one_way(policies, portfolio_frequency)
        eda.severity_overview(claims, pdf)
        eda.severity_one_way(claims_rated, pdf)

        # 3. frequency model --------------------------------------------------
        poisson_model = frequency.fit_poisson(policies)
        frequency.plot_frequency_heatmap(poisson_model, policies, pdf)

        # 4. severity models --------------------------------------------------
        gamma_model = severity.fit_gamma(claims_rated, pdf)
        lognormal_model = severity.fit_lognormal(claims_rated, pdf)
        severity.compare_models(claims_rated, gamma_model, lognormal_model, pdf)

        # 5. tariff and validation --------------------------------------------
        cells = pricing.tariff_table(policies, poisson_model, gamma_model, pdf)
        pricing.validate_tariff(cells, policies, claims)

    print("\nanalyse_plots.pdf and figures/pure_premium_heatmap.png written")


if __name__ == "__main__":
    main()
