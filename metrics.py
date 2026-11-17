"""Shared settings and helper functions.

Used by main.py and its modules, validation.py and features.py:
train/test split, GLM fitting, deviance, Gini, lift tables, plot style
and console section headers.
"""
import os

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
import statsmodels.api as sm
import statsmodels.formula.api as smf

SEED = 42
TEST_SHARE = 0.2
N_FOLDS = 5
LARGE_LOSS_THRESHOLD = 50_000   # claim amounts above this are capped (validation.py, section 4)
FREQ_FORMULA = "ClaimNb ~ age_group + bm_group"
SEV_FORMULA = "ClaimAmount ~ age_group + bm_group"

# plot colours (validated categorical palette: blue = model, orange = observed)
C_MODEL, C_OBS, C_REF = "#2a78d6", "#eb6834", "#8a8984"
# fixed categorical order for charts with more than two series
CATEGORICAL = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300"]
pd.set_option("display.width", 160)
pd.set_option("display.max_columns", 12)
plt.rcParams.update({"axes.spines.top": False, "axes.spines.right": False,
                     "axes.grid": True, "grid.alpha": 0.3, "font.size": 10})


def split_by_policy(policies, claims, test_share=TEST_SHARE, seed=SEED):
    """Random policy-level split; claims follow their policy."""
    rng = np.random.default_rng(seed)
    is_test = rng.random(len(policies)) < test_share
    test_ids = set(policies.loc[is_test, "IDpol"])
    test_mask_c = claims["IDpol"].isin(test_ids)
    return (policies[~is_test].copy(), policies[is_test].copy(),
            claims[~test_mask_c].copy(), claims[test_mask_c].copy())


def fit_frequency(data, formula=FREQ_FORMULA):
    """Poisson GLM, log link, log(Exposure) as offset."""
    return smf.glm(formula, data=data, family=sm.families.Poisson(),
                   offset=np.log(data["Exposure"])).fit()


def fit_severity(claims, formula=SEV_FORMULA):
    """Gamma GLM with log link on individual claim amounts."""
    return smf.glm(formula, data=claims,
                   family=sm.families.Gamma(link=sm.families.links.Log())).fit()


def poisson_deviance(y, mu):
    """Total Poisson deviance; the y*log(y/mu) term is 0 for y = 0."""
    y, mu = np.asarray(y, float), np.asarray(mu, float)
    term = np.where(y > 0, y * np.log(np.where(y > 0, y, 1) / mu), 0.0)
    return 2 * np.sum(term - (y - mu))


def gamma_deviance(y, mu):
    y, mu = np.asarray(y, float), np.asarray(mu, float)
    return 2 * np.sum((y - mu) / mu - np.log(y / mu))


def gini(actual, predicted, weight):
    """Gini index of the ordered Lorenz curve.

    Policies are sorted from lowest to highest predicted risk; the curve plots
    cumulative share of weight (exposure) against cumulative share of actual
    losses. Gini = 1 - 2 * area under the curve. 0 = no ranking power.
    """
    order = np.argsort(predicted, kind="stable")
    w = np.asarray(weight, float)[order]
    a = np.asarray(actual, float)[order]
    x = np.concatenate([[0], np.cumsum(w) / w.sum()])
    y = np.concatenate([[0], np.cumsum(a) / a.sum()])
    return 1 - 2 * np.trapezoid(y, x), x, y


def lift_table(actual, predicted_total, predicted_rate, exposure, n_bins=10):
    """Exposure-weighted bins by predicted rate: observed vs predicted per policy year."""
    df = pd.DataFrame({"actual": actual, "pred": predicted_total,
                       "rate": predicted_rate, "E": exposure}).sort_values("rate", kind="stable")
    cum_e = df["E"].cumsum() / df["E"].sum()
    df["bin"] = np.minimum((cum_e * n_bins).astype(int), n_bins - 1) + 1
    t = df.groupby("bin").agg(exposure=("E", "sum"), actual=("actual", "sum"),
                              predicted=("pred", "sum"))
    t["observed_rate"] = t["actual"] / t["exposure"]
    t["predicted_rate"] = t["predicted"] / t["exposure"]
    return t


def claim_cost_per_policy(policies, claims, amount_col="ClaimAmount"):
    cost = claims.groupby("IDpol")[amount_col].sum()
    return policies["IDpol"].map(cost).fillna(0.0).to_numpy()


def plot_lift(ax, t, title, ylabel):
    x = t.index.to_numpy()
    ax.plot(x, t["observed_rate"], marker="o", ms=6, lw=2, color=C_OBS, label="observed")
    ax.plot(x, t["predicted_rate"], marker="o", ms=6, lw=2, color=C_MODEL, label="predicted")
    ax.set_xticks(x)
    ax.set_xlabel("decile of predicted risk (equal exposure)")
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.legend(frameon=False)



def print_section(title):
    """Console header that separates the steps of a run."""
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


def pdf_pages(path):
    """PdfPages without a creation date: the same plots give a byte-identical
    file, so git only reports a change when a plot really changed."""
    return PdfPages(path, metadata={"CreationDate": None})


FIGURE_DIR = "figures"


def save_png(fig, name):
    """Save a figure for the README as figures/<name>.png."""
    os.makedirs(FIGURE_DIR, exist_ok=True)
    path = os.path.join(FIGURE_DIR, f"{name}.png")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    return path


def fit_frequency_agg(data, terms, formula=None):
    """Poisson GLM with log(Exposure) offset, fitted on aggregated cells.

    With categorical factors only, all policies in a cell share the same
    expected frequency. Summing ClaimNb and Exposure per cell gives the same
    likelihood up to a constant -> identical estimates, but much faster
    (checked: parameter differences < 1e-11 compared with the policy-level fit).
    """
    cells = (data.groupby(terms, observed=True)
             .agg(ClaimNb=("ClaimNb", "sum"), Exposure=("Exposure", "sum")).reset_index())
    formula = formula or "ClaimNb ~ " + " + ".join(terms)
    return smf.glm(formula, data=cells, family=sm.families.Poisson(),
                   offset=np.log(cells["Exposure"])).fit()
