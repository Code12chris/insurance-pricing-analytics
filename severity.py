"""Claim severity models: Gamma GLM vs. lognormal model.

Gamma GLM (log link): models the expected claim amount directly,
    E[Y] = exp(b0 + b_age + b_bm),  Var[Y] = phi * E[Y]^2
    -> constant coefficient of variation, the standard choice in pricing.

Lognormal model: linear regression on log(claim amount),
    log Y = b0 + b_age + b_bm + e,  e ~ N(0, sigma^2).
    Back-transformation needs a bias correction: E[Y] = exp(mu + sigma^2 / 2),
    because exp(E[log Y]) is the median, not the mean of Y.

Both are compared on how well they reproduce the observed mean claim amount
per tariff group. Result: the Gamma GLM is closer in every group, although
the lognormal model shows the Bonus-Malus effect with much smaller p-values.
Statistical significance of a factor is not the same as a good estimate of
the expected claim amount -- what pricing needs is the mean.
"""
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import statsmodels.api as sm
import statsmodels.formula.api as smf

from metrics import SEV_FORMULA, C_MODEL, C_REF, print_section

LABELS = {"age_group": "age group", "bm_group": "Bonus-Malus group"}


def fit_gamma(severity, pdf):
    """Gamma GLM, factor table, comparison per tariff cell and residual plots."""
    print_section("Claim severity: Gamma GLM (log link)")
    model = smf.glm(SEV_FORMULA, data=severity,
                    family=sm.families.Gamma(link=sm.families.links.Log())).fit()
    print(model.summary())

    factors = pd.DataFrame({"factor": np.exp(model.params), "p_value": model.pvalues})
    print("\nseverity factors (reference: age 18-25, Bonus-Malus <=50):")
    print(factors.round(3))
    # Reading the factors: drivers aged 26 and older have less than half the
    # expected claim amount of the youngest group. This effect rests largely on
    # the three claims above 1 million (all aged 18-20); with claims capped at
    # 50,000 it disappears (validation.py). The Bonus-Malus factors are not
    # significant: Bonus-Malus predicts how often, not how expensive.

    # observed vs. predicted mean claim amount per tariff cell
    cells = severity.assign(predicted=model.fittedvalues).groupby(
        ["age_group", "bm_group"], observed=True).agg(
        claims=("ClaimAmount", "size"), observed=("ClaimAmount", "mean"),
        predicted=("predicted", "mean"))
    cells["relative_error_%"] = 100 * (cells["predicted"] / cells["observed"] - 1)
    print("\nobserved vs. Gamma GLM mean claim amount per tariff cell:")
    print(cells.round(1))
    # Large cells are reproduced well; large relative errors occur in cells
    # with few claims. In 18-25 / 81-100 (all three claims above 1 million)
    # the model stays far below the observed mean, because it spreads the
    # effect of these claims over the whole age group.

    for x, y, xlabel, title in [
            (None, model.resid_deviance, "deviance residual", "Gamma GLM: deviance residuals"),
            (model.fittedvalues, model.resid_deviance, "predicted claim amount (EUR)",
             "Gamma GLM: deviance residuals vs. prediction")]:
        fig, ax = plt.subplots(figsize=(8, 5))
        if x is None:
            ax.hist(y, bins=100, color=C_MODEL)
            ax.set_ylabel("number of claims")
        else:
            ax.scatter(x, y, alpha=0.2, s=10, color=C_MODEL)
            ax.axhline(0, ls="--", color=C_REF)
            ax.set_ylabel("deviance residual")
        ax.set_xlabel(xlabel)
        ax.set_title(title)
        fig.tight_layout()
        pdf.savefig(fig)
        plt.close(fig)
    return model


def fit_lognormal(severity, pdf):
    """Linear model on log(claim amount) with diagnostic plots."""
    print_section("Claim severity: lognormal model (OLS on log claim amount)")
    data = severity.assign(log_claim=np.log(severity["ClaimAmount"]))
    model = smf.ols(SEV_FORMULA.replace("ClaimAmount", "log_claim"), data=data).fit()
    print(model.summary())

    ci = np.exp(model.conf_int())
    print("\nfactors on the median claim amount with 95% confidence interval:")
    print(pd.DataFrame({"factor": np.exp(model.params), "lower_95": ci[0],
                        "upper_95": ci[1]}).round(3))

    fitted, resid = model.fittedvalues, model.resid
    plots = [
        ("scatter", fitted, resid, "predicted log(claim amount)", "residual",
         "Lognormal model: residuals vs. prediction"),
        ("hist", None, resid, "residual", "number of claims",
         "Lognormal model: distribution of residuals"),
        ("scatter", fitted, np.sqrt(np.abs(resid)), "predicted log(claim amount)",
         r"$\sqrt{|residual|}$", "Lognormal model: scale-location plot"),
    ]
    for kind, x, y, xlabel, ylabel, title in plots:
        fig, ax = plt.subplots(figsize=(8, 5))
        if kind == "hist":
            ax.hist(y, bins=60, color=C_MODEL)
        else:
            ax.scatter(x, y, alpha=0.2, s=10, color=C_MODEL)
            if "scale" not in title:
                ax.axhline(0, ls="--", color=C_REF)
        ax.set_xlabel(xlabel)
        ax.set_ylabel(ylabel)
        ax.set_title(title)
        fig.tight_layout()
        pdf.savefig(fig)
        plt.close(fig)

    fig = sm.qqplot(resid[np.isfinite(resid)], line="45", fit=True)
    fig.axes[0].set_title("Lognormal model: Q-Q plot of residuals")
    fig.axes[0].get_lines()[0].set(color=C_MODEL, alpha=0.4)   # points
    fig.axes[0].get_lines()[1].set_color(C_REF)                 # reference line
    fig.tight_layout()
    pdf.savefig(fig)
    plt.close(fig)
    # Diagnostics: no funnel shape in the residual plots (variance roughly
    # constant on the log scale), but the Q-Q plot bends away from the line
    # at both ends: the tails are heavier than a normal distribution allows.
    return model


def compare_models(severity, gamma_model, lognormal_model, pdf):
    """Mean claim amount per group: observed vs. Gamma vs. lognormal.

    WMRAE (weighted mean relative absolute error) summarises a comparison
    table in one number: the absolute relative error of each group, weighted
    with the group's share of claims. Absolute values prevent over- and
    underestimates from cancelling out; the weights stop small groups with
    large random errors from dominating.
    The WMRAE is in-sample and measured on the same groups that are rating
    factors in the model, so it mainly shows calibration, not predictive power.
    """
    print_section("Claim severity: Gamma vs. lognormal")
    sigma2 = lognormal_model.mse_resid
    data = severity.assign(
        gamma_pred=gamma_model.fittedvalues,
        lognormal_pred=np.exp(lognormal_model.fittedvalues + sigma2 / 2))  # bias correction
    print(f"mean claim amount: observed {data['ClaimAmount'].mean():.2f}, "
          f"Gamma {data['gamma_pred'].mean():.2f}, lognormal {data['lognormal_pred'].mean():.2f}")

    results = {}
    for factor in ["age_group", "bm_group"]:
        t = data.groupby(factor, observed=True).agg(
            claims=("ClaimAmount", "size"), observed_mean=("ClaimAmount", "mean"),
            gamma_mean=("gamma_pred", "mean"), lognormal_mean=("lognormal_pred", "mean"))
        weights = t["claims"] / t["claims"].sum()
        wmrae = {m: 100 * (weights * (t[f"{m}_mean"] / t["observed_mean"] - 1).abs()).sum()
                 for m in ["gamma", "lognormal"]}
        print(f"\nby {factor}:")
        print(t.round(2))
        print(f"WMRAE Gamma {wmrae['gamma']:.2f}% | WMRAE lognormal {wmrae['lognormal']:.2f}%")
        results[factor] = (t, wmrae)

        fig, ax = plt.subplots(figsize=(8, 2.8))
        ax.axis("off")
        table = ax.table(cellText=t.round(0).astype(int).values, rowLabels=t.index,
                         colLabels=["claims", "observed", "Gamma", "lognormal"], loc="center")
        table.scale(1.2, 1.4)
        ax.set_title(f"Mean claim amount by {LABELS[factor]} (EUR)")
        fig.text(0.02, 0.02,
                 r"WMRAE $=\sum_g w_g\,|\hat{y}_g - y_g|\,/\,y_g$, $w_g$ = share of claims:  "
                 f"Gamma {wmrae['gamma']:.2f}%, lognormal {wmrae['lognormal']:.2f}%",
                 fontsize=9)
        pdf.savefig(fig, bbox_inches="tight")
        plt.close(fig)

    # Gamma dispersion: Pearson chi2 / df and deviance / df are not
    # goodness-of-fit measures to compare with 1 here, but estimates of the
    # dispersion phi. sqrt(phi) is the coefficient of variation: the standard
    # deviation of a claim relative to its expected value. The large gap
    # between the two estimates shows that a few extreme claims dominate.
    phi_pearson = gamma_model.pearson_chi2 / gamma_model.df_resid
    print(f"\nGamma dispersion: phi (Pearson) = {phi_pearson:.2f} -> coefficient of "
          f"variation {np.sqrt(phi_pearson):.2f}; deviance / df = "
          f"{gamma_model.deviance / gamma_model.df_resid:.2f}")
    return results
