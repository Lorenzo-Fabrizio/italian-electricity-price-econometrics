"""Controlli sulle trasformazioni, sugli stimatori e sul controfattuale."""

import numpy as np
import pandas as pd
import pytest

from src import config as cfg
from src import modelli as m

# La fixture ``df_raw`` (dataset sintetico) è definita in conftest.py.


def test_prepara_variabili_psv(df_raw):
    df = m.prepara_variabili(df_raw)
    # Il PSV parte a ottobre 2016: le variazioni partono da novembre 2016
    assert df.index.min() == pd.Timestamp(cfg.INIZIO_PSV) + pd.offsets.MonthBegin(1)
    assert df.index.max() == pd.Timestamp(cfg.FINE)
    assert m.dummy_mensili(df) == [f"M_{k}" for k in range(2, 13)]
    assert np.allclose(df["dlog_MC_CCGT"], np.log(df_raw["MC_CCGT_PSV"]).diff().loc[df.index])
    assert np.allclose(df["d_CDD"], df_raw["CDD"].diff().loc[df.index])


def test_prepara_variabili_ttf(df_raw):
    df = m.prepara_variabili(df_raw, gas="TTF")
    assert len(df) == len(df_raw) - 1                    # perde solo gennaio 2016
    assert np.allclose(df["dlog_MC_CCGT"], np.log(df_raw["MC_CCGT_TTF"]).diff().dropna())


def test_lag_hac_regola_newey_west(df_raw):
    for gas in ["PSV", "TTF"]:
        T = len(m.prepara_variabili(df_raw, gas=gas))
        assert int(np.floor(4 * (T / 100) ** (2 / 9))) == cfg.HAC_LAGS, gas


def test_2sls_coincide_con_ols_se_lo_strumento_e_il_regressore(df_raw):
    df = m.prepara_variabili(df_raw)
    regressori = ["dlog_MC_CCGT", "dlog_Residual_Load", "dlog_Hydro"]
    ols = m.stima_ols_hac(df, "dlog_PUN", regressori)
    iv = m.stima_2sls_hac(
        df, "dlog_PUN", "dlog_Residual_Load", ["dlog_MC_CCGT", "dlog_Hydro"], ["dlog_Residual_Load"]
    )
    tab = iv.tabella
    assert np.allclose(tab["coef"], ols.params[tab.index])
    assert np.allclose(tab["se HAC"], ols.bse[tab.index])


def test_2sls_coincide_con_linearmodels(df_raw):
    lm = pytest.importorskip("linearmodels.iv")
    df = m.prepara_variabili(df_raw)
    esogeni = ["dlog_MC_CCGT", "dlog_Hydro"]
    strumenti = ["d_CDD", "d_Giorni_lavorativi"]
    nostro = m.stima_2sls_hac(df, "dlog_PUN", "dlog_Residual_Load", esogeni, strumenti)

    W = df[esogeni + m.dummy_mensili(df)].assign(const=1.0)
    modello = lm.IV2SLS(df["dlog_PUN"], W, df[["dlog_Residual_Load"]], df[strumenti])
    rif = modello.fit(cov_type="kernel", kernel="bartlett", bandwidth=cfg.HAC_LAGS, debiased=False)

    tab = nostro.tabella
    assert np.allclose(tab["coef"], rif.params[tab.index])
    assert np.allclose(tab["se HAC"], rif.std_errors[tab.index], rtol=1e-6)
    classico = modello.fit(cov_type="unadjusted")
    assert nostro.diagnostica["Sargan p-value"] == pytest.approx(classico.sargan.pval, rel=1e-6)
    # linearmodels non corregge per i gradi di libertà: F = f.stat * (n - k) / n
    f_rif = classico.first_stage.diagnostics.loc["dlog_Residual_Load", "f.stat"]
    n, k = len(df), W.shape[1] + len(strumenti)
    assert nostro.diagnostica["F primo stadio (classico)"] == pytest.approx(f_rif * (n - k) / n, rel=1e-6)
    assert nostro.diagnostica["F primo stadio (classico)"] > 10      # strumenti rilevanti per costruzione


def test_dols_recupera_la_relazione_di_lungo_periodo():
    # Dati simulati cointegrati: y = 0.8 x + errore stazionario, x random walk
    rng = np.random.default_rng(0)
    idx = pd.date_range("2000-01-01", periods=400, freq="MS")
    x = np.cumsum(rng.normal(size=400))
    y = 0.8 * x + rng.normal(scale=0.5, size=400)
    livelli = pd.DataFrame({"y": y, "x": x}, index=idx)
    assert m.stima_dols(livelli, "y", ["x"], k=2).params["x"] == pytest.approx(0.8, abs=0.02)
    assert m.relazione_lungo_periodo(livelli, "y", ["x"]).params["x"] == pytest.approx(0.8, abs=0.02)


def test_controfattuale_nullo_se_beta_zero(df_raw):
    cf = m.controfattuale_add_back(df_raw, 0.0)
    assert np.allclose(cf["Risparmio_EUR_MWh"], 0)


def test_controfattuale_nullo_senza_vre():
    d = pd.DataFrame({"PUN": [100.0], "Demand": [20.0], "Residual_Load": [20.0]})
    assert m.controfattuale_add_back(d, 0.9)["Risparmio_EUR_MWh"].iloc[0] == 0


def test_controfattuale_unita():
    # 100 * (25/20)^1 = 125 EUR/MWh -> 25 EUR/MWh x 25 TWh = 625 milioni di euro
    d = pd.DataFrame({"PUN": [100.0], "Demand": [25.0], "Residual_Load": [20.0]})
    cf = m.controfattuale_add_back(d, 1.0)
    assert cf["PUN_senza_VRE"].iloc[0] == pytest.approx(125.0)
    assert cf["Risparmio_mln_EUR"].iloc[0] == pytest.approx(625.0)


def test_controfattuale_relativo_nullo_nell_anno_di_riferimento(df_raw):
    df = m.prepara_variabili(df_raw, gas="TTF")
    rl_cf = m.carico_residuo_quota_fissa(df, df_raw, anno=2016)
    cf = m.controfattuale_add_back(df, 0.9, rl_cf=rl_cf)
    assert np.allclose(cf.loc["2016", "Risparmio_EUR_MWh"], 0)


def test_controfattuale_beta_variabile(df_raw):
    beta = pd.Series(np.where(df_raw.index.year <= 2020, 1.0, 0.5), index=df_raw.index)
    cf = m.controfattuale_add_back(df_raw, beta)
    for anno, b in [(2018, 1.0), (2023, 0.5)]:
        atteso = m.controfattuale_add_back(df_raw, b).loc[str(anno)]
        assert np.allclose(cf.loc[str(anno), "PUN_senza_VRE"], atteso["PUN_senza_VRE"])
