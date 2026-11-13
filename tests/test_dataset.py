"""Controlli di coerenza sul dataset mensile reale (dati/elaborati).

Il dataset non è distribuito con il repository: se il file non c'è, questi
test vengono saltati. Si ricostruisce con ``python -m src.dati`` (dati/README.md).
"""

import numpy as np
import pandas as pd
import pytest

from src import config as cfg
from src import dati

# Media annua del PUN (EUR/MWh) pubblicata dal GME (statistiche annuali MGP)
PUN_ANNUO_GME = {
    2016: 42.78, 2017: 53.95, 2018: 61.31, 2019: 52.32, 2020: 38.92,
    2021: 125.46, 2022: 303.95, 2023: 127.24, 2024: 108.52,
}
COLONNE_PSV = ["Gas_PSV", "MC_CCGT_PSV"]

pytestmark = pytest.mark.skipif(
    not (cfg.ELABORATI / "dataset_mensile.csv").exists(),
    reason="dataset reale non presente: ricostruirlo con `python -m src.dati`",
)


@pytest.fixture(scope="module")
def df():
    return dati.carica_dataset()


def test_periodo_completo_senza_buchi(df):
    assert df.index.equals(pd.date_range(cfg.INIZIO, cfg.FINE, freq="MS"))
    assert list(df.columns) == dati.COLONNE
    # Gli unici valori mancanti ammessi sono il PSV prima del suo inizio
    prima_psv = df.index < pd.Timestamp(cfg.INIZIO_PSV)
    assert df.loc[prima_psv, COLONNE_PSV].isna().all().all()
    assert not df.loc[~prima_psv].isna().any().any()
    assert not df.drop(columns=COLONNE_PSV).isna().any().any()


def test_ore_per_mese(df):
    idx = df.index
    attese = idx.days_in_month * 24 - (idx.month == 3) + (idx.month == 10)
    assert (df["Ore"].to_numpy() == attese).all()


def test_pun_annuo_uguale_al_gme(df):
    anni = df.index.year
    media = (df["PUN"] * df["Ore"]).groupby(anni).sum() / df["Ore"].groupby(anni).sum()
    for anno, valore in PUN_ANNUO_GME.items():
        assert media[anno] == pytest.approx(valore, abs=0.005), anno


def test_ember_in_twh(df):
    # Valori Ember gennaio 2016 in TWh (la media con % e MtCO2e darebbe 1,70 e 3,56)
    gen16 = df.loc["2016-01-01"]
    assert gen16["Demand"] == pytest.approx(26.19)
    assert gen16["Solar"] == pytest.approx(0.92)
    assert gen16["Wind"] == pytest.approx(1.94)
    assert (df["Solar"] + df["Wind"] + df["Hydro"] < df["Demand"]).all()
    # Siccità 2022: anno con la produzione idroelettrica più bassa
    assert df["Hydro"].groupby(df.index.year).sum().idxmin() == 2022


def test_identita_variabili_derivate(df):
    assert np.allclose(df["VRE"], df["Solar"] + df["Wind"], atol=1e-3)
    assert np.allclose(df["Residual_Load"], df["Demand"] - df["VRE"], atol=1e-3)
    assert np.allclose(df["VRE_Share"], 100 * df["VRE"] / df["Demand"], atol=1e-3)
    for gas in ["PSV", "TTF"]:
        mc = df[f"Gas_{gas}"] / cfg.ETA_CCGT + cfg.EF_CCGT * df["CO2_EUA"]
        ok = mc.notna()
        assert np.allclose(df.loc[ok, f"MC_CCGT_{gas}"], mc[ok], atol=1e-3)


def test_nessuna_serie_ricostruita(df):
    # Prezzi senza tratti costanti (riempimento in avanti/indietro) e CO2 mai a zero.
    # Le quantità Ember sono arrotondate a 0,01 TWh: due mesi uguali sono possibili.
    for col in ["PUN", "Gas_PSV", "Gas_TTF", "CO2_EUA"]:
        s = df[col].dropna()
        assert (s.diff().iloc[1:] != 0).all(), col
    assert (df["CO2_EUA"] > 0).all()


def test_prezzi_plausibili(df):
    eua = df["CO2_EUA"].groupby(df.index.year).mean()
    assert eua[2016] < 10 and eua[2017] < 10
    assert 60 < eua[2022] < 100
    assert df["Gas_TTF"].idxmax().year == 2022
    assert df["Gas_PSV"].idxmax() == pd.Timestamp("2022-08-01")
    assert df["PUN"].idxmax() == pd.Timestamp("2022-08-01")
    assert df["Gas_PSV"].corr(df["Gas_TTF"]) > 0.95


def test_gradi_giorno_plausibili(df):
    assert (df[["HDD", "CDD"]] >= 0).all().all()
    assert (df.loc[df.index.month == 1, "CDD"] == 0).all()       # niente raffrescamento a gennaio
    assert (df.loc[df.index.month == 7, "HDD"] < df.loc[df.index.month == 7, "CDD"]).all()


def test_giorni_lavorativi(df):
    assert df["Giorni_lavorativi"].between(18, 23).all()
    # Contati a mano: gen 2016 = 21 feriali - 1 e 6 gennaio; mar 2016 = 23 - Pasquetta (28/3);
    # apr 2016 = 21 - 25 aprile
    assert df.loc["2016-01-01", "Giorni_lavorativi"] == 19
    assert df.loc["2016-03-01", "Giorni_lavorativi"] == 22
    assert df.loc["2016-04-01", "Giorni_lavorativi"] == 20


_GREZZI = [
    cfg.FILE_EMBER,
    cfg.FILE_WORLD_BANK,
    cfg.GREZZI / "fred" / "EXUSEU.csv",
    cfg.GREZZI / "eex" / "eua_auction_report_2012_2025.zip",
    cfg.GREZZI / "eurostat" / "nrg_chdd_m_IT.json",
]


@pytest.mark.skipif(
    not all(p.exists() for p in _GREZZI)
    or not any(cfg.GREZZI_GME_PUN.glob("Anno *.xlsx"))
    or not any(cfg.GREZZI_GME_GAS.glob("*.zip")),
    reason="dati grezzi non presenti",
)
def test_ricostruzione_dai_grezzi(df):
    nuovo = dati.costruisci_dataset(salva=False).round(4)
    pd.testing.assert_frame_equal(nuovo, df, check_dtype=False, check_freq=False)
