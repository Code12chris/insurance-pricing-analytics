"""Data loading, consistency checks and cleaning for freMTPL2.

Claim counts (ClaimNb in the policy table) and claim amounts (rows in the
claims table) must describe the same claims, otherwise frequency x severity
does not match the observed claim cost. consistency_report() documents why
the data is cleaned, clean() applies the rules. The same rules are
implemented in SQL (policies_analysis.sql, chapter 2) and compared by
check_sql_cleaning.py.
"""
import sqlite3

import numpy as np
import pandas as pd

AGE_BINS = [17, 25, 40, 60, 100]
AGE_LABELS = ["18-25", "26-40", "41-60", "61+"]
BM_BINS = [0, 50, 64, 80, 100, 125, 1000]
BM_LABELS = ["<=50", "51-64", "65-80", "81-100", "101-125", ">125"]
MAX_CLAIMS = 4


def load_raw(data_dir="data"):
    """Read the two freMTPL2 CSV files."""
    policies = pd.read_csv(f"{data_dir}/freMTPL2freq.csv")
    claims = pd.read_csv(f"{data_dir}/freMTPL2sev.csv")
    return policies, claims


def write_sqlite(policies, claims, db_path="insurance.db"):
    """Store the raw tables in SQLite (used by policies_analysis.sql) and read them back."""
    with sqlite3.connect(db_path) as con:
        policies.to_sql("policies", con, if_exists="replace", index=False)
        claims.to_sql("claims", con, if_exists="replace", index=False)
        policies = pd.read_sql_query("SELECT * FROM policies", con)
        claims = pd.read_sql_query("SELECT * FROM claims", con)
    print(f"SQLite database {db_path}: tables policies ({len(policies):,} rows) "
          f"and claims ({len(claims):,} rows)")
    return policies, claims


def consistency_report(policies, claims):
    """Print the checks that motivate the cleaning rules.

    Findings (the numbers are printed by this function):
    - The sum of ClaimNb is about 1.35 times the number of claim amounts.
    - Almost all claims without an amount sit in one block at the start of the
      data: all policies before the first claim-free policy have a claim, but
      hardly any amount, and an implausible frequency of about 2 per year.
      Outside the block counts and amounts match for more than 99.9%.
    - The claims without a policy belong to only a handful of policy numbers
      with dozens of claims each; their neighbouring numbers exist, so these
      are gaps in the policy table. Together with several policies with more
      than 4 claims and identical driver profiles this points to fleets, which
      are not individual risks.
    """
    n_amounts = claims.groupby("IDpol").size()
    amounts_per_policy = policies["IDpol"].map(n_amounts).fillna(0)
    block_end = policies.loc[policies["ClaimNb"] == 0, "IDpol"].min()
    in_block = policies["IDpol"] < block_end

    print(f"sum of ClaimNb: {policies['ClaimNb'].sum():,} | claim amounts: {len(claims):,} "
          f"| ratio {policies['ClaimNb'].sum() / len(claims):.3f}")

    segments = pd.DataFrame({
        "policies": [in_block.sum(), (~in_block).sum()],
        "policy_years": [policies.loc[in_block, "Exposure"].sum(),
                         policies.loc[~in_block, "Exposure"].sum()],
        "ClaimNb": [policies.loc[in_block, "ClaimNb"].sum(),
                    policies.loc[~in_block, "ClaimNb"].sum()],
        "claims_with_amount": [amounts_per_policy[in_block].sum(),
                               amounts_per_policy[~in_block].sum()]},
        index=[f"block IDpol < {block_end:.0f}", "rest of portfolio"])
    segments["share_with_amount"] = segments["claims_with_amount"] / segments["ClaimNb"]
    segments["frequency"] = segments["ClaimNb"] / segments["policy_years"]
    print(segments.round(4))

    orphan = claims[~claims["IDpol"].isin(policies["IDpol"])]
    ids = set(policies["IDpol"])
    by_id = orphan.groupby("IDpol")["ClaimAmount"].agg(claims="size", total="sum")
    by_id["neighbours_exist"] = [(i - 1 in ids) and (i + 1 in ids) for i in by_id.index]
    print(f"\nclaims without a policy: {len(orphan)} on {len(by_id)} policy numbers")
    print(by_id.sort_values("claims", ascending=False).round(0))

    many = policies[policies["ClaimNb"] > MAX_CLAIMS]
    print(f"\npolicies with more than {MAX_CLAIMS} claims:")
    print(many[["IDpol", "ClaimNb", "Exposure", "DrivAge", "BonusMalus", "VehBrand",
                "Region"]].to_string(index=False))
    print(f"policies with exposure above 1 year: {(policies['Exposure'] > 1).sum():,}")


def clean(policies, claims, verbose=True):
    """Return consistent (policies, claims): sum(ClaimNb) == number of claim rows.

    1. Drop the block of claim-only policies at the start of the data
       (all policies before the first claim-free policy; almost no amounts).
       The WHOLE block goes: dropping only its claim policies would keep the
       claim-free policies elsewhere and bias the frequency downwards.
    2. Drop remaining policies whose ClaimNb != number of recorded amounts.
    3. Drop policies with more than MAX_CLAIMS claims (likely fleets / errors).
       Dropped instead of capped: capping ClaimNb at 4 would leave up to 16
       claim amounts for 4 counted claims, i.e. inconsistent again.
    4. Cap exposure at 1 year (contracts run for at most one year).
    5. Drop claims without a policy and claims of dropped policies.
    """
    policies = policies.copy()
    n_sev = claims.groupby("IDpol").size()
    policies["n_sev"] = policies["IDpol"].map(n_sev).fillna(0).astype(int)

    block_end = policies.loc[policies["ClaimNb"] == 0, "IDpol"].min()
    keep = ((policies["IDpol"] >= block_end)
            & (policies["ClaimNb"] == policies["n_sev"])
            & (policies["ClaimNb"] <= MAX_CLAIMS))

    out = policies[keep].drop(columns="n_sev").copy()
    out["Exposure"] = out["Exposure"].clip(upper=1.0)
    claims_out = claims[claims["IDpol"].isin(out["IDpol"])].copy()

    assert out["ClaimNb"].sum() == len(claims_out)
    if verbose:
        print(f"cleaning: {len(policies):,} -> {len(out):,} policies, "
              f"{len(claims):,} -> {len(claims_out):,} claims "
              f"(block IDpol < {block_end:.0f} removed)")
    return out.reset_index(drop=True), claims_out.reset_index(drop=True)


def add_tariff_groups(policies):
    """Add the categorical rating factors age_group and bm_group."""
    policies = policies.copy()
    policies["age_group"] = pd.cut(policies["DrivAge"], AGE_BINS, labels=AGE_LABELS)
    policies["bm_group"] = pd.cut(policies["BonusMalus"], BM_BINS, labels=BM_LABELS)
    return policies


# --- additional rating factors (features.py) ------------------------------
# Bands are chosen from one-way claim frequencies on the training data:
# boundaries where the frequency changes, enough exposure per band.

DRIVAGE_BINS = [17, 20, 22, 25, 30, 40, 50, 60, 70, 100]
DRIVAGE_LABELS = ["18-20", "21-22", "23-25", "26-30", "31-40",
                  "41-50", "51-60", "61-70", "71+"]
VEHAGE_BINS = [-1, 4, 10, 15, 100]           # flat up to 10 years, falls after 15
VEHAGE_LABELS = ["0-4", "5-10", "11-15", "16+"]
VEHPOWER_BINS = [3, 4, 6, 8, 11, 100]        # power 4 lowest, 12+ sparse
VEHPOWER_LABELS = ["4", "5-6", "7-8", "9-11", "12+"]
# Density spans 1 to 27,000 inhabitants/km2 -> bands on the log scale,
# one band per unit of log(Density); the two lowest units are merged (0.5% exposure).
DENSITY_LOG_BINS = [-np.inf, 3, 4, 5, 6, 7, 8, 9, np.inf]
DENSITY_LABELS = ["<20", "20-55", "55-150", "150-400",
                  "400-1100", "1100-3000", "3000-8100", ">8100"]


def add_rating_features(policies):
    """Add banded versions of the remaining rating factors.

    Area is not banded again: it is itself a banding of log(Density)
    (non-overlapping ranges per class), so only one of the two may enter a model.
    """
    policies = policies.copy()
    policies["drivage_band"] = pd.cut(policies["DrivAge"], DRIVAGE_BINS, labels=DRIVAGE_LABELS)
    policies["vehage_band"] = pd.cut(policies["VehAge"], VEHAGE_BINS, labels=VEHAGE_LABELS)
    policies["vehpower_band"] = pd.cut(policies["VehPower"], VEHPOWER_BINS, labels=VEHPOWER_LABELS)
    policies["density_band"] = pd.cut(np.log(policies["Density"]), DENSITY_LOG_BINS,
                                      labels=DENSITY_LABELS)
    return policies


def group_small_regions(policies, small_regions):
    """Merge sparsely populated regions into 'Other' (list decided on training data)."""
    policies = policies.copy()
    policies["region_grp"] = policies["Region"].where(
        ~policies["Region"].isin(small_regions), "Other")
    return policies


def small_levels(policies, column, min_exposure_share=0.01):
    """Levels of `column` with less than `min_exposure_share` of total exposure."""
    share = policies.groupby(column)["Exposure"].sum() / policies["Exposure"].sum()
    return sorted(share[share < min_exposure_share].index)


def load_clean(data_dir="data", verbose=True):
    """Convenience: raw -> cleaned -> with tariff groups."""
    policies, claims = load_raw(data_dir)
    policies, claims = clean(policies, claims, verbose=verbose)
    return add_tariff_groups(policies), claims
