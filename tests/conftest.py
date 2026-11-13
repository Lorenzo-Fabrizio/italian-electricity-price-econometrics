"""Dati sintetici per i test dei modelli.

Il dataset reale non è distribuito con il repository (vedi dati/README.md):
i test sui modelli usano quindi un dataset simulato con la stessa struttura,
così girano anche su un clone pulito.
"""

import numpy as np
import pandas as pd
import pytest

from src import config as cfg
from src import dati


def dataset_sintetico(seed: int = 0) -> pd.DataFrame:
    """Dataset simulato con le stesse colonne, date e valori mancanti di quello reale."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range(cfg.INIZIO, cfg.FINE, freq="MS")
    n = len(idx)
    stagione = np.cos(2 * np.pi * (idx.month - 1) / 12)

    df = pd.DataFrame(index=idx)
    df["Ore"] = idx.days_in_month * 24 - (idx.month == 3) + (idx.month == 10)
    df["HDD"] = np.clip(150 + 150 * stagione + rng.normal(0, 20, n), 0, None)
    df["CDD"] = np.clip(-40 * stagione + rng.normal(0, 15, n), 0, None)
    df["Giorni_lavorativi"] = dati.giorni_lavorativi(idx)
    # La domanda dipende da caldo e giorni lavorativi: gli strumenti sono rilevanti
    df["Demand"] = (
        25 + 2 * stagione + 0.03 * df["CDD"] + 0.3 * (df["Giorni_lavorativi"] - 21)
        + rng.normal(0, 0.5, n)
    )
    df["Solar"] = 2.5 - 1.5 * stagione + rng.normal(0, 0.15, n)
    df["Wind"] = 1.7 + 0.4 * stagione + rng.normal(0, 0.3, n)
    df["Hydro"] = 3.5 - 1.0 * stagione + rng.normal(0, 0.4, n)
    df["Gas_TTF"] = 30 * np.exp(np.cumsum(rng.normal(0, 0.10, n)))
    df["Gas_PSV"] = df["Gas_TTF"] * np.exp(rng.normal(0.03, 0.05, n))
    df.loc[idx < pd.Timestamp(cfg.INIZIO_PSV), "Gas_PSV"] = np.nan
    df["CO2_EUA"] = 20 * np.exp(np.cumsum(rng.normal(0.01, 0.07, n)))
    df["VRE"] = df["Solar"] + df["Wind"]
    df["Residual_Load"] = df["Demand"] - df["VRE"]
    df["VRE_Share"] = 100 * df["VRE"] / df["Demand"]
    for gas in ["PSV", "TTF"]:
        df[f"MC_CCGT_{gas}"] = df[f"Gas_{gas}"] / cfg.ETA_CCGT + cfg.EF_CCGT * df["CO2_EUA"]
    # PUN: costo marginale (con il gas TTF, sempre disponibile), carico residuo e rumore
    df["PUN"] = (
        1.2 * df["MC_CCGT_TTF"] ** 0.9 * (df["Residual_Load"] / 21) ** 0.8
        * (df["Hydro"] / 3.5) ** -0.15 * np.exp(rng.normal(0, 0.05, n))
    )
    df.index.name = "Date"
    return df[dati.COLONNE]


@pytest.fixture(scope="session")
def df_raw() -> pd.DataFrame:
    return dataset_sintetico()
