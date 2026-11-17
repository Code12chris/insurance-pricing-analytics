"""Claim frequency model: Poisson GLM with age group and Bonus-Malus group.

    E[ClaimNb] = Exposure * exp(b0 + b_age + b_bm)
    log E[ClaimNb] = log(Exposure) + b0 + b_age + b_bm

log(Exposure) enters as an OFFSET: a term with a fixed coefficient of 1. The
model then describes claims per policy year, and a policy insured for half a
year is expected to have half the claims. Modelling the mean of ClaimNb
without the offset would mix short and long contracts.

exp(coefficient) is a multiplicative tariff factor relative to the reference
group (age 18-25, Bonus-Malus <=50). Example of reading it:
annual frequency of a driver aged 26-40 in Bonus-Malus 65-80
    = exp(b0) * exp(b_age 26-40) * exp(b_bm 65-80).
"""
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import statsmodels.api as sm
import statsmodels.formula.api as smf

from metrics import FREQ_FORMULA, print_section


def fit_poisson(policies):
    """Fit the Poisson GLM and print the tariff factors."""
    print_section("Claim frequency: Poisson GLM (age group + Bonus-Malus group)")
    model = smf.glm(FREQ_FORMULA, data=policies, family=sm.families.Poisson(),
                    offset=np.log(policies["Exposure"])).fit()
    print(model.summary())

    factors = pd.DataFrame({"coefficient": model.params,
                            "factor": np.exp(model.params),
                            "p_value": model.pvalues})
    print("\ntariff factors (Intercept = annual frequency of the reference group):")
    print(factors.round(3))

    # Pearson chi2 / df is printed for completeness only. With very small
    # expected counts (short exposure) a single claim adds a huge
    # (y - mu)^2 / mu, so the ratio is driven by a few short policies and is
    # no reliable overdispersion test -> see the Negative Binomial test in
    # validation.py.
    print(f"Pearson chi2 / df: {model.pearson_chi2 / model.df_resid:.3f}")

    # The GLM factor for Bonus-Malus is measured at equal age; the one-way
    # ratio mixes in the age effect, because young drivers have high
    # Bonus-Malus values. Comparison for the class 81-100:
    one_way = policies.groupby("bm_group", observed=True)[["ClaimNb", "Exposure"]].sum()
    one_way = one_way["ClaimNb"] / one_way["Exposure"]
    print(f"Bonus-Malus 81-100 vs <=50: one-way ratio {one_way['81-100'] / one_way['<=50']:.2f}, "
          f"GLM factor at equal age {np.exp(model.params['bm_group[T.81-100]']):.2f}")
    return model


def plot_frequency_heatmap(model, policies, pdf):
    """Expected annual claim frequency per tariff cell.

    model.predict() on a data frame does not apply the offset (it uses
    log(Exposure) = 0), so it returns the annual frequency directly.
    Dividing it by Exposure again would be wrong and inflate the values.
    """
    cells = (policies[["age_group", "bm_group"]].drop_duplicates()
             .sort_values(["age_group", "bm_group"]))
    cells["frequency"] = model.predict(cells)
    table = cells.pivot(index="age_group", columns="bm_group", values="frequency")

    fig, ax = plt.subplots(figsize=(8, 4))
    sns.heatmap(table, annot=True, fmt=".3f", cmap="Blues", ax=ax,
                cbar_kws={"label": "claims per policy year"})
    ax.set_title("Expected annual claim frequency (Poisson GLM)")
    ax.set_xlabel("Bonus-Malus group")
    ax.set_ylabel("age group")
    fig.tight_layout()
    pdf.savefig(fig)
    plt.close(fig)
    return table
