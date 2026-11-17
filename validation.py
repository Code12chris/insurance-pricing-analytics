"""Out-of-sample validation, overdispersion and large-loss analysis.

Run:  python validation.py
Output: console tables and validation_plots.pdf

Sections
1. Train/test split (policy level, fixed seed)
2. Frequency: out-of-sample Poisson deviance vs. null model, lift chart, Gini
3. Overdispersion: Negative Binomial (NB2), likelihood-ratio and Cameron-Trivedi test
4. Severity: Gamma dispersion, large-loss capping, out-of-sample Gamma deviance
5. Pure premium: out-of-sample lift chart, Gini and portfolio check
6. Stability: 5-fold cross-validation of the portfolio-level error
"""
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
import statsmodels.api as sm
import statsmodels.formula.api as smf
from scipy import stats

from data_prep import load_clean
from metrics import (SEED, TEST_SHARE, N_FOLDS, LARGE_LOSS_THRESHOLD, FREQ_FORMULA,
                     SEV_FORMULA, C_MODEL, C_OBS, C_REF, split_by_policy,
                     fit_frequency, fit_severity, poisson_deviance, gamma_deviance,
                     gini, lift_table, claim_cost_per_policy, plot_lift)

# ----------------------------------------------------------------------------
# 1. data and split
# ----------------------------------------------------------------------------

policies, claims = load_clean()
claims = claims.merge(policies[["IDpol", "age_group", "bm_group"]], on="IDpol")
train, test, train_c, test_c = split_by_policy(policies, claims)

print(f"\n=== 1. Train/test split (seed {SEED}, {TEST_SHARE:.0%} test) ===")
print(pd.DataFrame({
    "policies": [len(train), len(test)],
    "exposure": [train["Exposure"].sum(), test["Exposure"].sum()],
    "claims": [len(train_c), len(test_c)],
    "frequency": [len(train_c) / train["Exposure"].sum(), len(test_c) / test["Exposure"].sum()],
    "max_claim": [train_c["ClaimAmount"].max(), test_c["ClaimAmount"].max()]},
    index=["train", "test"]).round(4))

pdf = PdfPages("validation_plots.pdf")

# ----------------------------------------------------------------------------
# 2. frequency: out-of-sample deviance, lift, Gini
# ----------------------------------------------------------------------------

freq_null = fit_frequency(train, "ClaimNb ~ 1")
freq_model = fit_frequency(train)

rows = {}
for name, df in [("train (in-sample)", train), ("test (out-of-sample)", test)]:
    mu_null = freq_null.predict(df) * df["Exposure"]      # expected claim counts
    mu_model = freq_model.predict(df) * df["Exposure"]
    d_null = poisson_deviance(df["ClaimNb"], mu_null)
    d_model = poisson_deviance(df["ClaimNb"], mu_model)
    rows[name] = {"deviance_null": d_null, "deviance_model": d_model,
                  "D2_%": 100 * (1 - d_model / d_null),
                  "mean_dev_null": d_null / len(df), "mean_dev_model": d_model / len(df)}
freq_dev = pd.DataFrame(rows).T

print("\n=== 2. Frequency: Poisson deviance, model vs. null model (intercept only) ===")
print(freq_dev.round(5))

mu_test = freq_model.predict(test) * test["Exposure"]
freq_gini, gx, gy = gini(test["ClaimNb"], freq_model.predict(test), test["Exposure"])
freq_lift = lift_table(test["ClaimNb"], mu_test, freq_model.predict(test), test["Exposure"])
print(f"\nGini (frequency, test): {freq_gini:.3f}")
print("Lift table (test):")
print(freq_lift[["exposure", "observed_rate", "predicted_rate"]].round(4))

fig, axes = plt.subplots(1, 2, figsize=(12, 4.5))
plot_lift(axes[0], freq_lift, "Frequency lift chart (test set)", "claims per policy year")
axes[1].plot(gx, gy, lw=2, color=C_MODEL, label=f"Poisson GLM (Gini = {freq_gini:.3f})")
axes[1].plot([0, 1], [0, 1], lw=1.5, ls="--", color=C_REF, label="no ranking (Gini = 0)")
axes[1].set_xlabel("cumulative share of exposure (sorted by predicted frequency)")
axes[1].set_ylabel("cumulative share of claims")
axes[1].set_title("Ordered Lorenz curve, frequency (test set)")
axes[1].legend(frameon=False)
fig.tight_layout()
pdf.savefig(fig)
plt.close(fig)

# ----------------------------------------------------------------------------
# 3. overdispersion
# ----------------------------------------------------------------------------

print("\n=== 3. Overdispersion (train) ===")
pearson_df = freq_model.pearson_chi2 / freq_model.df_resid
pearson_contrib = freq_model.resid_pearson ** 2
short = train["Exposure"].to_numpy() < 0.05
print(f"Pearson chi2 / df: {pearson_df:.3f}")
print(f"  share of Pearson chi2 from policies with exposure < 0.05 "
      f"({short.mean():.1%} of policies): {pearson_contrib[short].sum() / pearson_contrib.sum():.1%}")
print(f"Deviance / df: {freq_model.deviance / freq_model.df_resid:.3f} "
      "(not chi2-distributed for small counts, no test either)")

# Negative Binomial NB2: Var(N) = mu + alpha * mu^2
# start from the Poisson estimates; without start values the optimiser diverges
nb = smf.negativebinomial(FREQ_FORMULA, data=train, offset=np.log(train["Exposure"])).fit(
    start_params=np.append(freq_model.params.to_numpy(), 0.5),
    method="newton", disp=0, maxiter=200)
assert nb.mle_retvals["converged"], "NB2 did not converge"
alpha = nb.params["alpha"]
lr = 2 * (nb.llf - freq_model.llf)
p_lr = 0.5 * stats.chi2.sf(lr, df=1)       # alpha = 0 lies on the boundary
print(f"\nNB2 alpha = {alpha:.3f}  (95% CI {nb.conf_int().loc['alpha', 0]:.3f} - "
      f"{nb.conf_int().loc['alpha', 1]:.3f})")
print(f"LR test Poisson vs NB2: LR = {lr:.1f}, p = {p_lr:.2e}")

# Cameron-Trivedi: regress ((y - mu)^2 - y) / mu on mu without intercept
mu_tr = freq_model.fittedvalues.to_numpy()
y_tr = train["ClaimNb"].to_numpy()
ct = sm.OLS(((y_tr - mu_tr) ** 2 - y_tr) / mu_tr, mu_tr).fit()
print(f"Cameron-Trivedi test: alpha_hat = {ct.params[0]:.3f}, t = {ct.tvalues[0]:.2f}")

mean_mu = (mu_tr / train["Exposure"]).mean()
print(f"Extra variance at a typical annual frequency of {mean_mu:.3f}: "
      f"alpha * mu = {alpha * mean_mu:.3f} -> Var(N) is {alpha * mean_mu:.1%} above Poisson")

coef_cmp = pd.DataFrame({
    "factor_poisson": np.exp(freq_model.params),
    "factor_nb2": np.exp(nb.params.drop("alpha")),
    "se_poisson": freq_model.bse,
    "se_nb2": nb.bse.drop("alpha"),
    "se_quasi_poisson": freq_model.bse * np.sqrt(pearson_df)})
print("\nRating factors and standard errors: Poisson vs NB2 vs Quasi-Poisson")
print(coef_cmp.round(4))

# ----------------------------------------------------------------------------
# 4. severity: dispersion, large losses, out-of-sample
# ----------------------------------------------------------------------------

print(f"\n=== 4. Severity (train), large-loss threshold {LARGE_LOSS_THRESHOLD:,} ===")
amt = train_c["ClaimAmount"]
n_large = (amt > LARGE_LOSS_THRESHOLD).sum()
excess = (amt - LARGE_LOSS_THRESHOLD).clip(lower=0).sum()
print(f"claims above threshold: {n_large} of {len(amt)} ({n_large / len(amt):.2%}), "
      f"excess = {excess / amt.sum():.1%} of total claim amount")
print("excess share for other thresholds:",
      {t: f"{(amt - t).clip(lower=0).sum() / amt.sum():.1%}" for t in [25_000, 100_000, 250_000]})

large_by_age = train_c.assign(large=amt > LARGE_LOSS_THRESHOLD).groupby(
    "age_group", observed=True).agg(claims=("large", "size"), large_claims=("large", "sum"))
large_by_age["large_per_1000_claims"] = 1000 * large_by_age["large_claims"] / large_by_age["claims"]
large_by_age["excess_share_%"] = 100 * train_c.assign(
    ex=(amt - LARGE_LOSS_THRESHOLD).clip(lower=0)).groupby("age_group", observed=True)["ex"].sum() / excess
print("Large losses by age group:")
print(large_by_age.round(2))

train_c["capped"] = amt.clip(upper=LARGE_LOSS_THRESHOLD)
test_c["capped"] = test_c["ClaimAmount"].clip(upper=LARGE_LOSS_THRESHOLD)
# large-loss loading: spread the excess over all claims proportionally
loading = excess / train_c["capped"].sum()
print(f"large-loss loading factor (uniform): 1 + {loading:.3f}")
# for comparison: loading if computed separately per age group (thin data!)
age_loading = (train_c.assign(ex=(amt - LARGE_LOSS_THRESHOLD).clip(lower=0))
               .groupby("age_group", observed=True)[["ex", "capped"]].sum())
print("loading if computed per age group:",
      (age_loading["ex"] / age_loading["capped"]).round(3).to_dict())

sev_full = fit_severity(train_c)
sev_cap = fit_severity(train_c, SEV_FORMULA.replace("ClaimAmount", "capped"))
sev_null_cap = fit_severity(train_c, "capped ~ 1")

for name, m in [("uncapped", sev_full), ("capped", sev_cap)]:
    phi_p = m.pearson_chi2 / m.df_resid
    phi_d = m.deviance / m.df_resid
    print(f"Gamma {name}: phi (Pearson) = {phi_p:.2f} -> CV = {np.sqrt(phi_p):.2f} ; "
          f"deviance/df = {phi_d:.2f}")
print(f"empirical CV of claim amounts: uncapped {amt.std() / amt.mean():.2f}, "
      f"capped {train_c['capped'].std() / train_c['capped'].mean():.2f}")

age_terms = [t for t in sev_full.params.index if t.startswith("age_group")]
factors = pd.DataFrame({
    "uncapped": np.exp(sev_full.params[age_terms]),
    "p_uncapped": sev_full.pvalues[age_terms],
    "capped": np.exp(sev_cap.params[age_terms]),
    "p_capped": sev_cap.pvalues[age_terms]})
print("\nAge severity factors relative to 18-25:")
print(factors.round(3))

d_null = gamma_deviance(test_c["capped"], sev_null_cap.predict(test_c))
d_cap = gamma_deviance(test_c["capped"], sev_cap.predict(test_c))
print(f"\nGamma deviance on test (capped amounts): null {d_null:,.0f}, "
      f"model {d_cap:,.0f}, D2 = {100 * (1 - d_cap / d_null):.2f}%")

fig, ax = plt.subplots(figsize=(7, 4))
x = np.arange(len(age_terms) + 1)
labels = ["18-25"] + [t.split("T.")[1].rstrip("]") for t in age_terms]
ax.bar(x - 0.2, [1] + list(factors["uncapped"]), width=0.38, color=C_OBS, label="uncapped claims")
ax.bar(x + 0.2, [1] + list(factors["capped"]), width=0.38, color=C_MODEL,
       label=f"claims capped at {LARGE_LOSS_THRESHOLD:,}")
ax.set_xticks(x, labels)
ax.set_xlabel("age group")
ax.set_ylabel("severity factor (18-25 = 1)")
ax.set_title("Gamma GLM age factors: effect of large-loss capping")
ax.set_ylim(0, 1.3)
ax.legend(frameon=False, ncol=2, loc="upper center")
fig.tight_layout()
pdf.savefig(fig)
plt.close(fig)

# ----------------------------------------------------------------------------
# 5. pure premium out-of-sample
# ----------------------------------------------------------------------------

print("\n=== 5. Pure premium on test set ===")
pp_cap = freq_model.predict(test) * sev_cap.predict(test) * (1 + loading)
pp_full = freq_model.predict(test) * sev_full.predict(test)
cost = claim_cost_per_policy(test, test_c)
cost_capped = claim_cost_per_policy(test, test_c, "capped")
E = test["Exposure"].to_numpy()

obs = cost.sum() / E.sum()
pp_rows = {}
for name, pp in [("uncapped Gamma", pp_full), ("capped Gamma + loading", pp_cap)]:
    mod = (pp * E).sum() / E.sum()
    pp_rows[name] = {"observed": obs, "modelled": mod, "error_%": 100 * (mod / obs - 1),
                     "gini_vs_cost": gini(cost, pp, E)[0],
                     "gini_vs_capped_cost": gini(cost_capped, pp, E)[0]}
print(pd.DataFrame(pp_rows).T.round(3))
print(f"observed test cost per policy year without large-loss excess: "
      f"{cost_capped.sum() / E.sum():.2f} vs modelled (capped, no loading) "
      f"{(pp_cap / (1 + loading) * E).sum() / E.sum():.2f}")

pp_lift = lift_table(cost_capped, pp_cap / (1 + loading) * E, pp_cap, E)
print("Pure premium lift table (test, capped claims, without loading):")
print(pp_lift[["exposure", "observed_rate", "predicted_rate"]].round(2))

fig, ax = plt.subplots(figsize=(7, 4.5))
plot_lift(ax, pp_lift, "Pure premium lift chart (test set, claims capped)",
          "claim cost per policy year (EUR)")
fig.tight_layout()
pdf.savefig(fig)
plt.close(fig)

# ----------------------------------------------------------------------------
# 6. stability: K-fold cross-validation
# ----------------------------------------------------------------------------

print(f"\n=== 6. {N_FOLDS}-fold cross-validation ===")
fold = np.random.default_rng(SEED).integers(0, N_FOLDS, len(policies))
cv_rows = []
for k in range(N_FOLDS):
    tr, te = policies[fold != k], policies[fold == k]
    tr_c = claims[claims["IDpol"].isin(tr["IDpol"])].copy()
    te_c = claims[claims["IDpol"].isin(te["IDpol"])].copy()
    tr_c["capped"] = tr_c["ClaimAmount"].clip(upper=LARGE_LOSS_THRESHOLD)
    te_c["capped"] = te_c["ClaimAmount"].clip(upper=LARGE_LOSS_THRESHOLD)
    load_k = ((tr_c["ClaimAmount"] - LARGE_LOSS_THRESHOLD).clip(lower=0).sum()
              / tr_c["capped"].sum())
    fm, fn = fit_frequency(tr), fit_frequency(tr, "ClaimNb ~ 1")
    sm_cap = fit_severity(tr_c, SEV_FORMULA.replace("ClaimAmount", "capped"))
    e = te["Exposure"].to_numpy()
    pp = fm.predict(te) * sm_cap.predict(te)
    obs_cost = claim_cost_per_policy(te, te_c).sum() / e.sum()
    obs_capped = claim_cost_per_policy(te, te_c, "capped").sum() / e.sum()
    cv_rows.append({
        "fold": k + 1,
        "freq_D2_%": 100 * (1 - poisson_deviance(te["ClaimNb"], fm.predict(te) * e)
                            / poisson_deviance(te["ClaimNb"], fn.predict(te) * e)),
        "largest_claim": te_c["ClaimAmount"].max(),
        "error_total_cost_%": 100 * ((pp * (1 + load_k) * e).sum() / e.sum() / obs_cost - 1),
        "error_capped_cost_%": 100 * ((pp * e).sum() / e.sum() / obs_capped - 1)})
cv = pd.DataFrame(cv_rows).set_index("fold")
print(cv.round(2))
print(cv.agg(["mean", "std"]).round(2))

fig, ax = plt.subplots(figsize=(7, 4))
x = cv.index.to_numpy()
ax.bar(x - 0.2, cv["error_total_cost_%"], width=0.38, color=C_OBS, label="total claim cost")
ax.bar(x + 0.2, cv["error_capped_cost_%"], width=0.38, color=C_MODEL,
       label=f"claims capped at {LARGE_LOSS_THRESHOLD:,}")
ax.axhline(0, color=C_REF, lw=1)
ax.set_xticks(x)
ax.set_xlabel("cross-validation fold")
ax.set_ylabel("modelled vs observed cost (%)")
ax.set_title("Portfolio error on held-out folds")
ax.legend(frameon=False)
fig.tight_layout()
pdf.savefig(fig)
plt.close(fig)

pdf.close()
print("\nvalidation_plots.pdf written")
