"""Trasformazioni, stime OLS-HAC, diagnostica e analisi controfattuale."""

from __future__ import annotations

from typing import NamedTuple

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats
from statsmodels.stats.diagnostic import (
    acorr_breusch_godfrey,
    acorr_ljungbox,
    het_breuschpagan,
)
from statsmodels.stats.outliers_influence import variance_inflation_factor
from statsmodels.stats.sandwich_covariance import S_hac_simple
from statsmodels.stats.stattools import durbin_watson
from statsmodels.tsa.stattools import adfuller

from . import config as cfg

VARIABILI_LOG = [
    "PUN", "MC_CCGT", "Gas", "CO2_EUA",
    "Residual_Load", "VRE_Share", "Demand", "Solar", "Wind", "VRE", "Hydro",
]
# Strumenti per la domanda: possono valere zero (CDD d'inverno), quindi differenze semplici.
VARIABILI_DIFF = ["HDD", "CDD", "Giorni_lavorativi"]


def prepara_variabili(df: pd.DataFrame, gas: str = "PSV") -> pd.DataFrame:
    """Aggiunge log-livelli, log-differenze (dlog_*), differenze degli strumenti (d_*)
    e dummy mensili (M_2..M_12).

    ``gas`` sceglie il prezzo del gas usato per ``Gas`` e ``MC_CCGT``:
    "PSV" (modello principale, variazioni da novembre 2016) oppure "TTF"
    (tutto il periodo, come nella tesi). Il primo mese disponibile si perde
    con la differenziazione.
    """
    out = df.copy()
    out["Gas"] = out[f"Gas_{gas}"]
    out["MC_CCGT"] = out[f"MC_CCGT_{gas}"]
    for col in VARIABILI_LOG:
        out[f"log_{col}"] = np.log(out[col])
        out[f"dlog_{col}"] = out[f"log_{col}"].diff()
    for col in VARIABILI_DIFF:
        out[f"d_{col}"] = out[col].diff()
    mesi = pd.get_dummies(out.index.month, prefix="M", drop_first=True, dtype=float)
    mesi.index = out.index
    out = pd.concat([out, mesi], axis=1)
    usate = [c for c in out.columns if c.startswith(("log_", "dlog_", "d_"))]
    return out.dropna(subset=usate)


def dummy_mensili(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns if c.startswith("M_")]


def test_adf(
    df: pd.DataFrame, colonne: list[str], regression: str = "c", alpha: float = 0.05
) -> pd.DataFrame:
    """Test Augmented Dickey-Fuller (H0: radice unitaria), lag scelti con AIC.

    ``regression``: "c" (costante) oppure "ct" (costante e trend lineare).
    """
    specifica = {"c": "costante", "ct": "costante + trend"}[regression]
    righe = []
    for c in colonne:
        stat, pval, lags, *_ = adfuller(df[c].dropna(), regression=regression, autolag="AIC")
        righe.append({
            "Variabile": c,
            "Specificazione": specifica,
            "ADF": round(stat, 3),
            "p-value": round(pval, 4),
            "Lag": lags,
            "Esito (5%)": "Stazionaria" if pval < alpha else "Radice unitaria non rifiutata",
        })
    return pd.DataFrame(righe).set_index("Variabile")


def stima_ols_hac(df: pd.DataFrame, y: str, regressori: list[str], lags: int = cfg.HAC_LAGS):
    """OLS con errori standard Newey-West (HAC). Le dummy mensili sono incluse."""
    X = sm.add_constant(df[regressori + dummy_mensili(df)])
    return sm.OLS(df[y], X).fit(cov_type="HAC", cov_kwds={"maxlags": lags})


def tabella_vif(modello) -> pd.DataFrame:
    """Variance Inflation Factor dei regressori (costante esclusa dalla tabella)."""
    X = pd.DataFrame(modello.model.exog, columns=modello.model.exog_names)
    idx = [i for i, c in enumerate(X.columns) if c != "const"]
    return pd.DataFrame(
        {"VIF": [variance_inflation_factor(X.values, i) for i in idx]},
        index=X.columns[idx],
    ).round(2)


def diagnostica(modello) -> pd.Series:
    """Test sui residui: autocorrelazione, eteroschedasticità, normalità."""
    ols = sm.OLS(modello.model.endog, modello.model.exog).fit()  # stessi residui, s.e. classici
    lm, lm_p, _, _ = het_breuschpagan(modello.resid, modello.model.exog)
    return pd.Series({
        "Durbin-Watson": durbin_watson(modello.resid),
        "Breusch-Godfrey(4) p-value": acorr_breusch_godfrey(ols, nlags=4)[1],
        "Ljung-Box(12) p-value": acorr_ljungbox(modello.resid, lags=[12])["lb_pvalue"].iloc[0],
        "Breusch-Pagan p-value": lm_p,
        "Jarque-Bera p-value": sm.stats.jarque_bera(modello.resid)[1],
        "R2": modello.rsquared,
        "R2 corretto": modello.rsquared_adj,
        "Osservazioni": int(modello.nobs),
    }).round(4)


def relazione_lungo_periodo(livelli: pd.DataFrame, y: str, x: list[str]):
    """Regressione statica in livelli con costante e dummy mensili (primo passo di
    Engle-Granger). I residui ritardati sono il termine di correzione dell'errore."""
    D = pd.get_dummies(livelli.index.month, prefix="M", drop_first=True, dtype=float)
    D.index = livelli.index
    return sm.OLS(livelli[y], sm.add_constant(pd.concat([livelli[x], D], axis=1))).fit()


def stima_dols(livelli: pd.DataFrame, y: str, x: list[str], k: int = 1, lags: int = cfg.HAC_LAGS):
    """Dynamic OLS (Stock e Watson, 1993) della relazione di lungo periodo.

    Regressione in livelli con costante, dummy mensili e ``k`` anticipi e ritardi
    delle differenze dei regressori, che correggono la distorsione della stima
    statica; errori standard HAC. I coefficienti di ``x`` sono le elasticità di
    lungo periodo.
    """
    D = pd.get_dummies(livelli.index.month, prefix="M", drop_first=True, dtype=float)
    D.index = livelli.index
    dX = livelli[x].diff()
    anticipi_ritardi = [dX.shift(-j).add_suffix(f"_d{j:+d}") for j in range(-k, k + 1)]
    Z = pd.concat([livelli[x], D] + anticipi_ritardi, axis=1).dropna()
    return sm.OLS(livelli.loc[Z.index, y], sm.add_constant(Z)).fit(
        cov_type="HAC", cov_kwds={"maxlags": lags}
    )


class RisultatoIV(NamedTuple):
    tabella: pd.DataFrame      # coefficienti, errori standard HAC, p-value, IC 95%
    diagnostica: pd.Series     # forza degli strumenti, Hausman, Sargan


def stima_2sls_hac(
    df: pd.DataFrame,
    y: str,
    endogena: str,
    esogeni: list[str],
    strumenti: list[str],
    lags: int = cfg.HAC_LAGS,
) -> RisultatoIV:
    """Minimi quadrati a due stadi (2SLS) con errori standard Newey-West (HAC).

    Costante e dummy mensili entrano in entrambi gli stadi insieme a ``esogeni``.
    La covarianza HAC è calcolata come in ``stima_ols_hac`` (kernel di Bartlett,
    nessuna correzione per piccoli campioni), usando i residui strutturali
    y - X b; con strumenti = [endogena] il risultato coincide con l'OLS.

    Diagnostica:
    * F del primo stadio sugli strumenti esclusi (classico e robusto HAC);
    * test di Durbin-Wu-Hausman nella forma con funzione di controllo: il residuo
      del primo stadio aggiunto all'equazione OLS, t-test HAC (H0: regressore esogeno);
    * test di sovraidentificazione (H0: strumenti validi): Sargan, non robusto, e
      J di Hansen con matrice dei pesi HAC.
    """
    W = sm.add_constant(df[esogeni + dummy_mensili(df)])           # esogeni inclusi
    X = pd.concat([W[["const"]], df[[endogena]], W.drop(columns="const")], axis=1)
    Z = pd.concat([W[["const"]], df[strumenti], W.drop(columns="const")], axis=1)
    Z = Z.loc[:, ~Z.columns.duplicated()]

    primo = sm.OLS(df[endogena], Z).fit()
    X_hat = X.copy()
    X_hat[endogena] = primo.fittedvalues
    beta = np.linalg.lstsq(X_hat.to_numpy(), df[y].to_numpy(), rcond=None)[0]
    u = df[y].to_numpy() - X.to_numpy() @ beta

    H_inv = np.linalg.inv(X_hat.T.to_numpy() @ X_hat.to_numpy())
    S = S_hac_simple(X_hat.to_numpy() * u[:, None], nlags=lags)
    se = np.sqrt(np.diag(H_inv @ S @ H_inv))
    z = beta / se
    q = stats.norm.ppf(0.975)
    tabella = pd.DataFrame(
        {"coef": beta, "se HAC": se, "z": z, "p-value": 2 * stats.norm.sf(np.abs(z)),
         "IC 2,5%": beta - q * se, "IC 97,5%": beta + q * se},
        index=X.columns,
    )

    esclusi = [s for s in strumenti if s not in X.columns]
    diag = {}
    if esclusi:   # senza strumenti esclusi (caso OLS) i test non sono definiti
        vincoli = ", ".join(f"{s} = 0" for s in esclusi)
        primo_hac = sm.OLS(df[endogena], Z).fit(cov_type="HAC", cov_kwds={"maxlags": lags})
        controllo = sm.OLS(df[y], X.assign(residuo_primo_stadio=primo.resid)).fit(
            cov_type="HAC", cov_kwds={"maxlags": lags}
        )
        diag["F primo stadio (classico)"] = float(primo.f_test(vincoli).fvalue)
        diag["F primo stadio (HAC)"] = (
            float(primo_hac.wald_test(vincoli, scalar=True).statistic) / len(esclusi)
        )
        diag["Hausman p-value"] = controllo.pvalues["residuo_primo_stadio"]
    gdl = Z.shape[1] - X.shape[1]
    if gdl > 0:
        n = len(u)
        r2 = sm.OLS(u, Z).fit().rsquared
        diag["Sargan p-value"] = stats.chi2.sf(n * r2, gdl)
        # J di Hansen: GMM efficiente in due passi con matrice dei pesi HAC (robusto)
        Zv, Xv, yv = Z.to_numpy(), X.to_numpy(), df[y].to_numpy()
        pesi = np.linalg.inv(S_hac_simple(Zv * u[:, None], nlags=lags) / n)
        A = Xv.T @ Zv @ pesi
        b_gmm = np.linalg.solve(A @ Zv.T @ Xv, A @ Zv.T @ yv)
        g = Zv.T @ (yv - Xv @ b_gmm) / n
        diag["Hansen J p-value (HAC)"] = stats.chi2.sf(n * g @ pesi @ g, gdl)
    diag["Osservazioni"] = len(u)
    return RisultatoIV(tabella, pd.Series(diag))


def controfattuale_add_back(
    df: pd.DataFrame, beta: float | pd.Series, rl_cf: pd.Series | None = None
) -> pd.DataFrame:
    """Scenario controfattuale con il metodo add-back.

    Nel modello log-log beta è l'elasticità del PUN al carico residuo, quindi
    portando il carico residuo da RL al valore controfattuale RL_cf:

        PUN_cf = PUN * (RL_cf / Residual_Load) ** beta

    Di default RL_cf = Demand, cioè lo scenario senza VRE. ``beta`` può essere
    una serie con un valore per mese (elasticità diversa per periodo).

    Il risparmio monetario è (PUN_cf - PUN) * Demand; con Demand in TWh e
    prezzi in EUR/MWh il prodotto è in milioni di euro.
    """
    if rl_cf is None:
        rl_cf = df["Demand"]
    out = pd.DataFrame(index=df.index)
    out["PUN"] = df["PUN"]
    out["PUN_senza_VRE"] = df["PUN"] * (rl_cf / df["Residual_Load"]) ** beta
    out["Risparmio_EUR_MWh"] = out["PUN_senza_VRE"] - out["PUN"]
    out["Risparmio_mln_EUR"] = out["Risparmio_EUR_MWh"] * df["Demand"]
    return out


def carico_residuo_quota_fissa(df: pd.DataFrame, df_raw: pd.DataFrame, anno: int = 2016) -> pd.Series:
    """Carico residuo con la quota di VRE ferma al livello dello stesso mese di ``anno``.

    RL_cf = Demand * (1 - VRE/Demand dello stesso mese di ``anno``). Usato come
    ``rl_cf`` in ``controfattuale_add_back`` misura l'effetto della sola crescita
    delle VRE rispetto ad ``anno``.
    """
    rif = df_raw.loc[str(anno)]
    quota = pd.Series((rif["VRE"] / rif["Demand"]).to_numpy(), index=rif.index.month)
    if len(quota) != 12:
        raise ValueError(f"L'anno di riferimento {anno} non ha 12 mesi")
    return df["Demand"] * (1 - quota.reindex(df.index.month).to_numpy())
