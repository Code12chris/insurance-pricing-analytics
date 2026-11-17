"""Tariff: pure premium per tariff cell and validation against observed costs.

    pure premium = expected annual claim frequency x expected claim amount

The frequency comes from the Poisson GLM, the claim amount from the Gamma GLM.
Both models use only age group and Bonus-Malus group, so the tariff has
4 x 6 = 24 cells. features.py extends this with further rating factors.
"""
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns

from metrics import C_MODEL, print_section, save_png


def tariff_table(policies, poisson_model, gamma_model, pdf):
    """Predict frequency, severity and pure premium for every tariff cell."""
    print_section("Tariff: pure premium per tariff cell")
    cells = policies.groupby(["age_group", "bm_group"], observed=True).agg(
        policies=("IDpol", "count"), policy_years=("Exposure", "sum")).reset_index()
    cells["frequency"] = poisson_model.predict(cells)        # annual frequency (no offset)
    cells["severity"] = gamma_model.predict(cells)
    cells["pure_premium"] = cells["frequency"] * cells["severity"]
    print(cells.round(3).to_string(index=False))

    matrix = cells.pivot(index="age_group", columns="bm_group", values="pure_premium")
    fig, ax = plt.subplots(figsize=(8, 5))
    sns.heatmap(matrix, annot=True, fmt=".0f", cmap="Blues", ax=ax,
                cbar_kws={"label": "EUR per policy year"})
    ax.set_title("Expected pure premium by tariff cell (EUR per policy year)")
    ax.set_xlabel("Bonus-Malus group")
    ax.set_ylabel("age group")
    fig.tight_layout()
    save_png(fig, "pure_premium_heatmap")
    pdf.savefig(fig)
    plt.close(fig)

    fig, axes = plt.subplots(2, 2, figsize=(12, 8), sharey=True)
    for ax, (age, group) in zip(axes.flatten(), cells.groupby("age_group", observed=True)):
        ax.bar(group["bm_group"].astype(str), group["pure_premium"], color=C_MODEL)
        ax.set_title(f"age {age}")
        ax.set_xlabel("Bonus-Malus group")
        ax.set_ylabel("EUR per policy year")
        ax.tick_params(axis="x", rotation=30)
    fig.suptitle("Expected pure premium by age group and Bonus-Malus group")
    fig.tight_layout()
    pdf.savefig(fig)
    plt.close(fig)
    return cells


def validate_tariff(cells, policies, claims):
    """Compare the tariff with observed claim costs per cell and for the portfolio.

    Observed pure premium of a cell = total claim amount / policy years.
    Policies are insured for different parts of a year, so every comparison
    weights with exposure: the portfolio value is
        sum(pure premium_i * exposure_i) / sum(exposure_i).

    What the numbers mean:
    - Large deviations in single cells come mainly from small cells and from
      18-25, where the three claims above 1 million sit in one cell but the
      model spreads them over the whole age group.
    - The portfolio deviation is close to 0 almost by construction: a Poisson
      GLM with log link reproduces the total claim count exactly in-sample,
      the Gamma GLM nearly reproduces the total claim amount. It shows that
      frequency and severity data are consistent (before the data cleaning it
      was +31.9%), NOT that the model predicts well. Predictive quality is
      measured out-of-sample in validation.py.
    """
    print_section("Tariff validation against observed claim costs")
    amounts = claims.merge(policies[["IDpol", "age_group", "bm_group"]], on="IDpol")
    observed = amounts.groupby(["age_group", "bm_group"], observed=True)["ClaimAmount"].sum()

    check = cells.set_index(["age_group", "bm_group"])
    check["observed_pure_premium"] = observed.reindex(check.index).fillna(0) / check["policy_years"]
    check["relative_error_%"] = 100 * (check["pure_premium"] / check["observed_pure_premium"] - 1)
    print(check[["policies", "pure_premium", "observed_pure_premium", "relative_error_%"]].round(1))

    weighted_error = ((check["policy_years"] * check["relative_error_%"].abs()).sum()
                      / check["policy_years"].sum())

    E = policies["Exposure"].sum()
    observed_portfolio = claims["ClaimAmount"].sum() / E
    cell_premium = check["pure_premium"].rename("pp").reset_index()
    pp = policies[["age_group", "bm_group", "Exposure"]].merge(cell_premium, on=["age_group", "bm_group"])
    modelled_portfolio = (pp["pp"] * pp["Exposure"]).sum() / E

    summary = pd.Series({
        "observed portfolio claim cost (EUR per policy year)": observed_portfolio,
        "modelled portfolio pure premium (EUR per policy year)": modelled_portfolio,
        "portfolio relative error (%)": 100 * (modelled_portfolio / observed_portfolio - 1),
        "exposure-weighted tariff-cell error (%)": weighted_error})
    print("\nPortfolio validation:")
    print(summary.round(2).to_string())
    return summary
