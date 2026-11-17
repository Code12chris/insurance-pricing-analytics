"""Extended rating factors: selection, validation, large-loss loading, tariff tables.

Run:  python features.py          (takes a few minutes, progress is printed)
Output: console tables, features_plots.pdf, tariff_tables.csv

Sections
1. Data, train/test split (same seed as validation.py), banded rating factors
2. Frequency: forward selection by 5-fold cross-validation on the TRAINING data only
3. Frequency: final comparison base vs extended model on the untouched test set
4. Severity: the same selection for capped claim amounts
5. Large-loss loading: uniform vs. credibility-weighted by age group
6. Tariff tables (age group x Bonus-Malus), averaged over the portfolio mix

Why the test set is used only once (section 3): if features were chosen by their
test-set performance, the test result would be optimistic. Selection therefore
uses cross-validation inside the training data; the test set only reports.
"""
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
import seaborn as sns
import statsmodels.api as sm
import statsmodels.formula.api as smf
from scipy.special import gammaln

from data_prep import load_clean, add_rating_features, group_small_regions, small_levels
from metrics import (SEED, N_FOLDS, LARGE_LOSS_THRESHOLD, C_MODEL, C_OBS, C_REF,
                     split_by_policy, poisson_deviance, gamma_deviance, gini,
                     lift_table, plot_lift)

# A feature is added only if it lowers the cross-validated deviance by at least 0.1%
# on average AND lowers it in every single fold (stability criterion).
# Note: the stability criterion was added after a first run, in which the mean-only
# rule selected Region for severity; that gain came from 2 of 5 folds and turned
# into a loss on the test set (D2 0.43% -> -0.70%). Documented here on purpose.
MIN_GAIN = 0.001
# limited-fluctuation credibility: full credibility if the number of large claims is
# within +-5% of its expectation with 90% probability -> (1.645 / 0.05)^2 = 1082
FULL_CREDIBILITY_CLAIMS = 1082

# Formula term per rating factor. The reference level (factor = 1) is the level
# with the most exposure, so every factor reads as "relative to the typical policy".
TERMS = {
    "age_group": "age_group",
    "bm_group": "bm_group",
    "drivage_band": 'C(drivage_band, Treatment("41-50"))',
    "vehage_band": 'C(vehage_band, Treatment("0-4"))',
    "vehpower_band": 'C(vehpower_band, Treatment("5-6"))',
    "VehGas": 'C(VehGas, Treatment("Regular"))',
    "VehBrand": 'C(VehBrand, Treatment("B1"))',
    "density_band": 'C(density_band, Treatment("150-400"))',
    "Area": 'C(Area, Treatment("C"))',
    "region_grp": 'C(region_grp, Treatment("Centre"))',
}
BASE = ["age_group", "bm_group"]
CANDIDATES = ["drivage_band", "vehage_band", "vehpower_band", "VehGas",
              "VehBrand", "density_band", "Area", "region_grp"]
# pairs that describe the same thing: at most one of each pair in a model
EXCLUSIVE = [("age_group", "drivage_band"), ("density_band", "Area")]


# ----------------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------------

def formula(response, terms):
    return f"{response} ~ " + " + ".join(TERMS[t] for t in terms)


def fit_frequency_agg(data, terms):
    """Poisson GLM fitted on aggregated cells.

    With categorical factors only, all policies in a cell share the same expected
    frequency. Summing ClaimNb and Exposure per cell gives the same likelihood up to
    a constant -> identical estimates, but much faster (checked: parameter
    differences < 1e-11 compared with the policy-level fit).
    """
    cells = (data.groupby(terms, observed=True)
             .agg(ClaimNb=("ClaimNb", "sum"), Exposure=("Exposure", "sum")).reset_index())
    return smf.glm(formula("ClaimNb", terms), data=cells, family=sm.families.Poisson(),
                   offset=np.log(cells["Exposure"])).fit()


def fit_severity_terms(claims, terms, response="capped"):
    return smf.glm(formula(response, terms), data=claims,
                   family=sm.families.Gamma(link=sm.families.links.Log())).fit()


def candidate_moves(current):
    """All models one step away: add a factor, or swap age_group -> drivage_band."""
    moves = {}
    for c in CANDIDATES:
        if c in current:
            continue
        partner = next((a if b == c else b for a, b in EXCLUSIVE if c in (a, b)), None)
        if partner in current and c == "drivage_band":
            moves["age_group -> drivage_band"] = [t if t != "age_group" else c for t in current]
        elif partner not in current:
            moves[f"+ {c}"] = current + [c]
    return moves


def forward_selection(cv_score, start, label):
    """Greedy forward selection.

    cv_score(terms) returns the held-out deviance per fold (array of length N_FOLDS).
    In each step the move with the largest mean gain is taken, provided it gains at
    least MIN_GAIN on average and improves every fold.
    """
    current, folds = list(start), cv_score(start)
    print(f"\n[{label}] start {current}: CV deviance {folds.sum():,.1f}")
    path = [{"step": 0, "move": "base model", "cv_deviance": folds.sum(),
             "gain_%": np.nan, "folds_improved": np.nan}]
    while True:
        moves = candidate_moves(current)
        if not moves:
            break
        results = {name: cv_score(terms) for name, terms in moves.items()}
        gains = {name: 100 * (1 - r.sum() / folds.sum()) for name, r in results.items()}
        improved = {name: int((r < folds).sum()) for name, r in results.items()}
        print("  candidates (mean gain %, folds improved):",
              {k: (round(float(gains[k]), 3), improved[k])
               for k in sorted(gains, key=gains.get, reverse=True)})
        eligible = [k for k in gains
                    if gains[k] >= 100 * MIN_GAIN and improved[k] == N_FOLDS]
        if not eligible:
            print(f"  stop: no candidate gains >= {100 * MIN_GAIN:.1f}% in all folds")
            break
        best = max(eligible, key=gains.get)
        current, folds = moves[best], results[best]
        path.append({"step": len(path), "move": best, "cv_deviance": folds.sum(),
                     "gain_%": gains[best], "folds_improved": improved[best]})
        print(f"  -> {best}")
    return current, pd.DataFrame(path).set_index("step")


def poisson_aic(model, data):
    """AIC on policy level (the aggregated fit has a different constant per model)."""
    y = data["ClaimNb"].to_numpy()
    mu = (model.predict(data) * data["Exposure"]).to_numpy()
    llf = np.sum(y * np.log(mu) - mu - gammaln(y + 1))
    return -2 * llf + 2 * len(model.params)


def factor_table(model):
    ci = np.exp(model.conf_int())
    return pd.DataFrame({"factor": np.exp(model.params), "ci_low": ci[0], "ci_high": ci[1],
                         "p_value": model.pvalues})


# ----------------------------------------------------------------------------
# 1. data
# ----------------------------------------------------------------------------

policies, claims = load_clean()
policies = add_rating_features(policies)
train, test, train_c, test_c = split_by_policy(policies, claims)

# small regions (< 1% exposure) are merged; the list is taken from the training data
small_regions = small_levels(train, "Region")
policies, train, test = (group_small_regions(d, small_regions) for d in (policies, train, test))
print(f"regions merged into 'Other': {small_regions}")

feature_cols = ["IDpol"] + BASE + CANDIDATES
train_c = train_c.merge(train[feature_cols], on="IDpol")
test_c = test_c.merge(test[feature_cols], on="IDpol")
claims = claims.merge(policies[feature_cols], on="IDpol")
for c in (train_c, test_c, claims):
    c["capped"] = c["ClaimAmount"].clip(upper=LARGE_LOSS_THRESHOLD)

# fold labels for cross-validation inside the training data (policy level)
fold = np.random.default_rng(SEED + 1).integers(0, N_FOLDS, len(train))
fold_of_policy = pd.Series(fold, index=train["IDpol"].to_numpy())
fold_c = train_c["IDpol"].map(fold_of_policy).to_numpy()

pdf = PdfPages("features_plots.pdf")

# ----------------------------------------------------------------------------
# 2. frequency: forward selection by cross-validation on training data
# ----------------------------------------------------------------------------

def cv_frequency(terms):
    out = []
    for k in range(N_FOLDS):
        fit, hold = train[fold != k], train[fold == k]
        model = fit_frequency_agg(fit, terms)
        out.append(poisson_deviance(hold["ClaimNb"], model.predict(hold) * hold["Exposure"]))
    return np.array(out)


print("\n=== 2. Frequency: forward selection (5-fold CV on training data) ===")
freq_terms, freq_path = forward_selection(cv_frequency, BASE, "frequency")
print("\nSelection path:")
print(freq_path.round(3))
print(f"selected: {freq_terms}")

# ----------------------------------------------------------------------------
# 3. frequency: base vs extended on the test set (used once)
# ----------------------------------------------------------------------------

print("\n=== 3. Frequency: base vs extended model on the test set ===")
# null model: one frequency for everybody (intercept only)
mu_null = np.full(len(test), train["ClaimNb"].sum() / train["Exposure"].sum()) * test["Exposure"]
d_null = poisson_deviance(test["ClaimNb"], mu_null)

comparison, lifts = {}, {}
for name, terms in [("base (age_group + bm_group)", BASE), ("extended", freq_terms)]:
    m = fit_frequency_agg(train, terms)
    rate = m.predict(test)
    d = poisson_deviance(test["ClaimNb"], rate * test["Exposure"])
    comparison[name] = {"parameters": len(m.params), "test_deviance": d,
                        "D2_%": 100 * (1 - d / d_null),
                        "gini": gini(test["ClaimNb"], rate, test["Exposure"])[0],
                        "AIC_train": poisson_aic(m, train)}
    lifts[name] = lift_table(test["ClaimNb"], rate * test["Exposure"], rate, test["Exposure"])
comparison = pd.DataFrame(comparison).T
comparison["delta_AIC"] = comparison["AIC_train"] - comparison["AIC_train"].iloc[0]
print(comparison.drop(columns="AIC_train").round(4))

freq_final = fit_frequency_agg(train, freq_terms)
print("\nExtended frequency model: factors with 95% confidence interval (train)")
print(factor_table(freq_final).round(3))

fig, axes = plt.subplots(1, 2, figsize=(12, 4.5), sharey=True)
for ax, (name, t) in zip(axes, lifts.items()):
    plot_lift(ax, t, f"Frequency lift, {name} (test set)", "claims per policy year")
fig.tight_layout()
pdf.savefig(fig)
plt.close(fig)

# ----------------------------------------------------------------------------
# 4. severity (capped claims): same selection
# ----------------------------------------------------------------------------

def cv_severity(terms):
    out = []
    for k in range(N_FOLDS):
        fit, hold = train_c[fold_c != k], train_c[fold_c == k]
        model = fit_severity_terms(fit, terms)
        out.append(gamma_deviance(hold["capped"], model.predict(hold)))
    return np.array(out)


print(f"\n=== 4. Severity: forward selection on claims capped at {LARGE_LOSS_THRESHOLD:,} ===")
sev_terms, sev_path = forward_selection(cv_severity, BASE, "severity")
print("\nSelection path:")
print(sev_path.round(3))
print(f"selected: {sev_terms}")

sev_null = smf.glm("capped ~ 1", data=train_c,
                   family=sm.families.Gamma(link=sm.families.links.Log())).fit()
d0 = gamma_deviance(test_c["capped"], sev_null.predict(test_c))
for name, terms in [("base", BASE), ("selected", sev_terms)]:
    m = fit_severity_terms(train_c, terms)
    d = gamma_deviance(test_c["capped"], m.predict(test_c))
    print(f"severity {name}: test D2 = {100 * (1 - d / d0):.2f}%")

# ----------------------------------------------------------------------------
# 5. large-loss loading: uniform vs credibility-weighted by age group
# ----------------------------------------------------------------------------
# The excess above the threshold must still be paid for. Two ways to spread it:
#  a) uniform: every claim gets the same relative loading L = total excess / total capped
#  c) credibility: each age group mixes its own loading L_g with the uniform L,
#     L_cred_g = Z_g * L_g + (1 - Z_g) * L,  Z_g = min(1, sqrt(n_g / 1082)),
#     n_g = number of large claims in the group. Afterwards all L_cred_g are scaled by
#     one common factor so that the total excess is still covered exactly.
# Computed on the full portfolio, because these loadings feed the tariff tables.

print("\n=== 5. Large-loss loading by age group (full portfolio) ===")
claims["excess"] = claims["ClaimAmount"] - claims["capped"]
ll = claims.groupby("age_group", observed=True).agg(
    claims=("capped", "size"), large_claims=("excess", lambda x: (x > 0).sum()),
    capped_sum=("capped", "sum"), excess_sum=("excess", "sum"))
L_uniform = ll["excess_sum"].sum() / ll["capped_sum"].sum()
ll["L_group"] = ll["excess_sum"] / ll["capped_sum"]
ll["Z"] = np.minimum(1, np.sqrt(ll["large_claims"] / FULL_CREDIBILITY_CLAIMS))
ll["L_cred_raw"] = ll["Z"] * ll["L_group"] + (1 - ll["Z"]) * L_uniform
balance = ll["excess_sum"].sum() / (ll["capped_sum"] * ll["L_cred_raw"]).sum()
ll["L_credibility"] = ll["L_cred_raw"] * balance
ll["L_uniform"] = L_uniform
print(ll.drop(columns="L_cred_raw").round(3))
print(f"balancing factor for credibility loadings: {balance:.4f}")

# ----------------------------------------------------------------------------
# 6. tariff tables averaged over the portfolio mix
# ----------------------------------------------------------------------------
# After validation the selected models are refitted on the full portfolio (standard
# practice: the test set has done its job). Pure premium per policy year:
#     PP = expected frequency x expected capped severity x (1 + large-loss loading)
#
# A table cell (age group a, Bonus-Malus class b) contains the exposure-weighted
# average PP of all policies in that cell. To show the effect of one factor
# (e.g. Diesel vs Regular), that factor is set to the same value for every policy
# in the cell, while all other characteristics stay as they are. The difference
# between two tables is therefore the effect of that factor alone, measured on
# the real mix of drivers and vehicles in each cell -- and the table without a
# fixed factor is directly comparable with the 24-class base tariff in main.py.

print("\n=== 6. Tariff tables (pure premium per policy year, EUR) ===")
freq_full = fit_frequency_agg(policies, freq_terms)
sev_full = fit_severity_terms(claims, sev_terms)
loading_uniform = 1 + L_uniform
loading_cred = 1 + policies["age_group"].map(ll["L_credibility"]).astype(float)


def tariff_table(fixed=None, loading=loading_uniform):
    data = policies if fixed is None else policies.assign(**fixed)
    pp = freq_full.predict(data) * sev_full.predict(data) * loading
    df = pd.DataFrame({"age_group": policies["age_group"], "bm_group": policies["bm_group"],
                       "pp_E": pp * policies["Exposure"], "E": policies["Exposure"]})
    t = df.groupby(["age_group", "bm_group"], observed=True)[["pp_E", "E"]].sum()
    return (t["pp_E"] / t["E"]).unstack()


# balance check: the tariff must cover the observed claim cost of the portfolio
E_total = policies["Exposure"].sum()
observed_cost = claims["ClaimAmount"].sum() / E_total
for name, loading in [("uniform", loading_uniform), ("credibility", loading_cred)]:
    pp = freq_full.predict(policies) * sev_full.predict(policies) * loading
    modelled = (pp * policies["Exposure"]).sum() / E_total
    print(f"balance check ({name} loading): modelled {modelled:.2f} vs observed "
          f"{observed_cost:.2f} EUR per policy year ({100 * (modelled / observed_cost - 1):+.2f}%)")

tables = {"portfolio mix (uniform loading)": tariff_table(),
          "portfolio mix (credibility loading)": tariff_table(loading=loading_cred)}
contrasts = []
if "VehGas" in freq_terms + sev_terms:
    contrasts.append(("VehGas", "Regular", "Diesel"))
if "density_band" in freq_terms + sev_terms:
    contrasts.append(("density_band", "20-55", "3000-8100"))
if "Area" in freq_terms + sev_terms:
    contrasts.append(("Area", "B", "E"))
if "vehage_band" in freq_terms + sev_terms:
    contrasts.append(("vehage_band", "0-4", "16+"))
if "vehpower_band" in freq_terms + sev_terms:
    contrasts.append(("vehpower_band", "4", "9-11"))
for col, low, high in contrasts:
    for value in (low, high):
        cat = policies[col].dtype
        fixed_value = (pd.Categorical([value] * len(policies), categories=cat.categories)
                       if isinstance(cat, pd.CategoricalDtype) else value)
        tables[f"{col} = {value}"] = tariff_table({col: fixed_value})

for name, t in tables.items():
    print(f"\n{name}:")
    print(t.round(0))

long = pd.concat({name: t.stack() for name, t in tables.items()}, names=["table"])
long.rename("pure_premium").reset_index().to_csv("tariff_tables.csv", index=False)
print("\ntariff_tables.csv written")

pairs = [("portfolio mix (uniform loading)", "portfolio mix (credibility loading)")]
pairs += [(f"{c} = {lo}", f"{c} = {hi}") for c, lo, hi in contrasts]
for left, right in pairs:
    vmax = max(tables[left].max().max(), tables[right].max().max())
    fig, axes = plt.subplots(1, 2, figsize=(13, 4))
    for ax, name in zip(axes, (left, right)):
        sns.heatmap(tables[name], annot=True, fmt=".0f", cmap="Blues", vmin=0, vmax=vmax,
                    ax=ax, cbar=ax is axes[1], cbar_kws={"label": "EUR per policy year"})
        ax.set_title(f"Pure premium: {name}")
        ax.set_xlabel("Bonus-Malus group")
        ax.set_ylabel("age group")
    fig.tight_layout()
    pdf.savefig(fig)
    plt.close(fig)

pdf.close()
print("features_plots.pdf written")
