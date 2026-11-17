"""Exploratory data analysis of claim frequency and claim severity.

Each function prints its tables, adds its plots to the open PDF and returns
the tables that later steps need. Interpretations are written next to the
code that produces the evidence; all numbers are computed, none are typed in.
"""
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from scipy.stats import poisson

from metrics import C_MODEL, C_OBS, CATEGORICAL, print_section

QUANTILES = [0.50, 0.75, 0.90, 0.95, 0.99]
LABELS = {"age_group": "age group", "bm_group": "Bonus-Malus group"}


# ----------------------------------------------------------------------------
# claim frequency
# ----------------------------------------------------------------------------

def frequency_overview(policies, pdf):
    """Claim count distribution, portfolio frequency and a Poisson check.

    The claim frequency is claims per policy year: sum(ClaimNb) / sum(Exposure).
    The plain mean of ClaimNb is NOT the frequency, because policies are
    insured for different parts of a year (mean exposure is about half a year).
    """
    print_section("Claim frequency: overview")
    counts = policies["ClaimNb"].value_counts().sort_index()
    print(pd.DataFrame({"policies": counts,
                        "share_%": (100 * counts / counts.sum()).round(2)}))

    frequency = policies["ClaimNb"].sum() / policies["Exposure"].sum()
    print(f"\nclaims: {policies['ClaimNb'].sum():,} | policy years: "
          f"{policies['Exposure'].sum():,.0f} | annual claim frequency: {frequency:.4f}")
    print(f"mean exposure per policy: {policies['Exposure'].mean():.3f} years")

    # Poisson check: compare observed shares with a Poisson distribution of the
    # same mean. Variance / mean close to 1 is compatible with Poisson.
    # This is only a first look: it ignores the different exposures; the proper
    # overdispersion test (Negative Binomial) is in validation.py.
    mean, var = policies["ClaimNb"].mean(), policies["ClaimNb"].var()
    print(f"ClaimNb: mean {mean:.4f}, variance {var:.4f}, variance / mean {var / mean:.2f}")

    k = np.arange(0, policies["ClaimNb"].max() + 1)
    observed = policies["ClaimNb"].value_counts(normalize=True).reindex(k, fill_value=0)
    expected = poisson.pmf(k, mean)

    fig, axes = plt.subplots(1, 2, figsize=(12, 4))
    for ax, title, ylim in [(axes[0], "all claim counts", None),
                            (axes[1], "zoom on policies with claims", 0.055)]:
        ax.scatter(k, observed, s=60, color=C_OBS, label="observed", zorder=3)
        ax.plot(k, expected, ls="--", color=C_MODEL, label="Poisson (same mean)")
        ax.set_xticks(k)
        ax.set_xlabel("number of claims per policy")
        ax.set_ylabel("share of policies")
        ax.set_title(title)
        if ylim:
            ax.set_ylim(0, ylim)
        ax.legend(frameon=False)
    fig.suptitle("Claim counts: observed vs. Poisson distribution")
    fig.tight_layout()
    pdf.savefig(fig)
    plt.close(fig)
    # Observation: slightly fewer policies with exactly one claim and slightly
    # more with two claims than Poisson predicts -> a hint of heterogeneity
    # between risks, which rating factors are meant to explain.
    return frequency


def frequency_by_factor(policies, factor, portfolio_frequency):
    """One-way table: frequency and relativity to the portfolio per group."""
    t = policies.groupby(factor, observed=True).agg(
        policies=("IDpol", "count"), claims=("ClaimNb", "sum"),
        policy_years=("Exposure", "sum"))
    t["frequency"] = t["claims"] / t["policy_years"]
    t["relativity"] = t["frequency"] / portfolio_frequency
    print(f"\nfrequency by {factor}:")
    print(t.round(4))
    return t


def frequency_one_way(policies, portfolio_frequency):
    """Frequency by age group and by Bonus-Malus group.

    - Young drivers (18-25) have about twice the portfolio frequency.
    - Bonus-Malus separates much more strongly: the classes above 100 reach
      several times the portfolio frequency, but contain few policies, so
      their values are less certain.
    - French Bonus-Malus: 50 is the best value (0.5 x base premium), 100 the
      starting level (1.0 x), above 100 a malus after claims. It works in the
      opposite direction to the German SF classes.
    One-way tables mix effects: young drivers also have high Bonus-Malus
    values. The GLM separates the two (frequency.py).
    """
    print_section("Claim frequency by rating factor (one-way)")
    age = frequency_by_factor(policies, "age_group", portfolio_frequency)
    bm = frequency_by_factor(policies, "bm_group", portfolio_frequency)
    return age, bm


# ----------------------------------------------------------------------------
# claim severity
# ----------------------------------------------------------------------------

def severity_overview(claims, pdf):
    """Distribution of claim amounts and the largest claims.

    Mean far above median -> strongly right-skewed. On a log scale the amounts
    look roughly normal, which suggests a lognormal distribution; the Gamma
    GLM (standard for severity) and a lognormal model are compared in
    severity.py.
    """
    print_section("Claim severity: overview")
    amounts = claims["ClaimAmount"]
    print(amounts.describe().round(2))
    print(f"missing amounts: {amounts.isna().sum()} | amounts <= 0: {(amounts <= 0).sum()}")

    fig, ax = plt.subplots(figsize=(8, 4))
    ax.hist(np.log10(amounts), bins=60, color=C_MODEL)
    ax.set_xlabel("log10(claim amount in EUR)")
    ax.set_ylabel("number of claims")
    ax.set_title("Distribution of claim amounts (log scale)")
    fig.tight_layout()
    pdf.savefig(fig)
    plt.close(fig)

    print("\nclaims above threshold:")
    for t in [10_000, 50_000, 100_000, 500_000, 1_000_000]:
        n = (amounts > t).sum()
        print(f"  > {t:>9,} EUR: {n:5d} claims ({100 * n / len(amounts):.3f}%)")
    print("largest 10 claims:", amounts.nlargest(10).round(0).astype(int).tolist())
    # A few claims above 1 million among about 26,000 claims: rare, but
    # plausible for motor liability (bodily injury). They are kept and treated
    # as large losses (capping and loading) in validation.py / features.py.


def severity_by_factor(severity, factor, pdf):
    """Mean, median and upper quantiles of the claim amount per group.

    If the medians are similar but the means differ, the difference comes from
    the right tail. The ratio of neighbouring quantiles ("tail growth") shows
    where the distribution stretches out.
    """
    stats = severity.groupby(factor, observed=True)["ClaimAmount"].agg(
        claims="count", mean="mean", median="median")
    quant = severity.groupby(factor, observed=True)["ClaimAmount"].quantile(QUANTILES).unstack()
    growth = pd.DataFrame({
        f"{int(100 * hi)}% / {int(100 * lo)}%": quant[hi] / quant[lo]
        for lo, hi in zip(QUANTILES[:-1], QUANTILES[1:])})
    print(f"\nseverity by {factor}:")
    print(stats.round(0))
    print("quantiles:")
    print(quant.round(0))
    print("tail growth (ratio of neighbouring quantiles):")
    print(growth.round(2))
    print("99% / 50% quantile:", (quant[0.99] / quant[0.50]).round(1).to_dict())

    fig, ax = plt.subplots(figsize=(8, 4))
    growth.plot(kind="bar", ax=ax, width=0.8, color=CATEGORICAL[:growth.shape[1]])
    ax.set_ylabel("ratio of neighbouring quantiles")
    ax.set_xlabel(LABELS[factor])
    ax.set_title(f"Tail growth of claim amounts by {LABELS[factor]}")
    ax.tick_params(axis="x", rotation=0)
    ax.legend(frameon=False, ncol=4, loc="upper center", bbox_to_anchor=(0.5, -0.18))
    fig.tight_layout()
    pdf.savefig(fig)
    plt.close(fig)
    return stats


def severity_one_way(severity, pdf):
    """Severity by age group and Bonus-Malus group.

    Findings:
    - Medians are almost identical in all groups: a typical claim costs about
      the same for every driver.
    - The means differ, above all for 18-25. The tail growth shows why: up to
      the 95% quantile the groups behave alike, above it the young drivers'
      claims grow much faster. A few extreme claims pull the mean up (the
      three claims above 1 million all belong to drivers aged 18-20).
    - Bonus-Malus has no monotone effect on severity; the class >125 has only
      a few hundred claims, so its values are uncertain.
    """
    print_section("Claim severity by rating factor (one-way)")
    age = severity_by_factor(severity, "age_group", pdf)
    bm = severity_by_factor(severity, "bm_group", pdf)
    return age, bm
