"""Data loading, consistency checks and cleaning for freMTPL2.

Same cleaning rules as the data-consistency section in main.py:
claim counts (ClaimNb) and claim amounts must describe the same claims.
"""
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


def clean(policies, claims, verbose=True):
    """Return consistent (policies, claims): sum(ClaimNb) == number of claim rows.

    1. Drop the block of claim-only policies at the start of the data
       (all policies before the first claim-free policy; almost no amounts).
    2. Drop remaining policies whose ClaimNb != number of recorded amounts.
    3. Drop policies with more than MAX_CLAIMS claims (likely fleets / errors).
    4. Cap exposure at 1 year.
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


def load_clean(data_dir="data", verbose=True):
    """Convenience: raw -> cleaned -> with tariff groups."""
    policies, claims = load_raw(data_dir)
    policies, claims = clean(policies, claims, verbose=verbose)
    return add_tariff_groups(policies), claims
