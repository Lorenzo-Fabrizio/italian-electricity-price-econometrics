"""Costruzione del dataset mensile a partire dalle fonti originali.

Fonti
-----
* PUN : GME, esiti MGP orari ("Anno AAAA*.xlsx", foglio "Prezzi-Prices").
* Domanda, solare, eolico, idroelettrico : Ember, "Monthly electricity data"
  (Europa, formato long).
* Gas PSV : GME, mercati a pronti del gas (MGAS), prezzo medio ponderato
  giornaliero (foglio "DATI SBILANCIAMENTO" dei file "Anno termico").
* Gas TTF (specificazione alternativa) : World Bank, Pink Sheet mensile, colonna
  "Natural gas, Europe" (USD/MMBtu; dall'aprile 2015 è il prezzo Netherlands TTF),
  convertita in EUR/MWh con il cambio mensile FRED EXUSEU.
* CO2 (EUA) : EEX, prezzi di aggiudicazione delle aste primarie EUA (EUR/tCO2).
* Gradi-giorno (HDD, CDD) : Eurostat, tabella ``nrg_chdd_m`` (Italia).

Uso da riga di comando (rigenera ``dati/elaborati/dataset_mensile.csv``)::

    python -m src.dati
"""

from __future__ import annotations

import io
import json
import re
import urllib.request
import zipfile
from pathlib import Path

import pandas as pd
from dateutil.easter import easter

from . import config as cfg

FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}&cosd=2015-01-01"
EEX_ARCHIVE_URL = (
    "https://www.eex.com/fileadmin/EEX/Downloads/Markets/Environmentals/"
    "EUA_Emission_Spot_Primary_Market_Auction_Report/Archive_Reports/"
    "emission-spot-primary-market-auction-report-2012-2025-data.zip"
)
EUROSTAT_HDD_URL = (
    "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/"
    "nrg_chdd_m?format=JSON&lang=EN&geo=IT&sinceTimePeriod=2015-12"
)

# Ordine delle colonne del dataset finale
COLONNE = [
    "PUN", "Ore", "Demand", "Solar", "Wind", "Hydro",
    "Gas_PSV", "Gas_TTF", "CO2_EUA", "HDD", "CDD", "Giorni_lavorativi",
    "VRE", "Residual_Load", "VRE_Share", "MC_CCGT_PSV", "MC_CCGT_TTF",
]


def _download(url: str, dest: Path, user_agent: str | None = None) -> Path:
    """Scarica ``url`` in ``dest`` se il file non esiste già (cache locale)."""
    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        headers = {"User-Agent": user_agent} if user_agent else {}
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=120) as r:
            dest.write_bytes(r.read())
    return dest


# ---------------------------------------------------------------------------
# PUN (GME)
# ---------------------------------------------------------------------------
def _pun_orario(path: Path) -> pd.Series:
    df = pd.read_excel(path, sheet_name="Prezzi-Prices")
    col_data = next(c for c in df.columns if "data" in str(c).lower())
    col_pun = next(c for c in df.columns if "pun" in str(c).lower())
    date = pd.to_datetime(df[col_data].astype(str), format="%Y%m%d")
    return pd.Series(df[col_pun].to_numpy(dtype=float), index=date)


def carica_pun() -> pd.DataFrame:
    """PUN mensile (media dei prezzi orari, EUR/MWh) e numero di ore del mese.

    Per il 2025 il GME fornisce due file (quarti d'ora ``_15`` e orario ``_60``)
    con le stesse medie mensili: si usa quello orario, coerente con gli anni
    precedenti. Il numero di ore serve per le medie annue ponderate, che così
    coincidono con le medie annue pubblicate dal GME.
    """
    files = sorted(p for p in cfg.GREZZI_GME_PUN.glob("Anno *.xlsx") if not p.stem.endswith("_15"))
    if not files:
        raise FileNotFoundError(f"Nessun file 'Anno *.xlsx' in {cfg.GREZZI_GME_PUN}")
    orario = pd.concat([_pun_orario(f) for f in files]).sort_index()
    mensile = pd.DataFrame({
        "PUN": orario.resample("MS").mean(),
        "Ore": orario.resample("MS").size(),
    })
    # Controllo: ore attese = giorni x 24, -1 a marzo e +1 a ottobre (ora legale).
    # Un file duplicato o incompleto farebbe fallire il controllo.
    idx = mensile.index
    attese = idx.days_in_month * 24 - (idx.month == 3) + (idx.month == 10)
    if (mensile["Ore"].to_numpy() != attese).any():
        raise ValueError("Numero di ore mensili inatteso nei file GME (file duplicati o incompleti?)")
    return mensile


# ---------------------------------------------------------------------------
# Domanda e generazione (Ember)
# ---------------------------------------------------------------------------
def carica_ember_italia(path: Path = cfg.FILE_EMBER) -> pd.DataFrame:
    """Domanda e generazione solare, eolica e idroelettrica mensile in Italia (TWh).

    Il file Ember riporta la stessa variabile in più unità (TWh, %, MtCO2e):
    è indispensabile filtrare ``Unit == 'TWh'`` prima del pivot.
    """
    variabili = ["Demand", "Solar", "Wind", "Hydro"]
    df = pd.read_csv(path, usecols=["ISO 3 code", "Date", "Category", "Variable", "Unit", "Value"])
    df = df[
        (df["ISO 3 code"] == "ITA")
        & (df["Unit"] == "TWh")
        & (df["Category"].isin(["Electricity demand", "Electricity generation"]))
        & (df["Variable"].isin(variabili))
    ]
    if df.duplicated(["Date", "Variable"]).any():
        raise ValueError("Righe duplicate per (Date, Variable) nel file Ember")
    wide = df.pivot(index="Date", columns="Variable", values="Value")
    wide.index = pd.to_datetime(wide.index)
    wide.columns.name = None
    return wide[variabili]


# ---------------------------------------------------------------------------
# Gas al PSV (GME): prezzo del gas del modello principale
# ---------------------------------------------------------------------------
def _psv_giornaliero(zpath: Path) -> pd.Series:
    """Prezzo medio ponderato giornaliero dal foglio "DATI SBILANCIAMENTO"."""
    with zipfile.ZipFile(zpath) as z:
        nomi = [n for n in z.namelist() if n.lower().endswith(".xlsx")]
        if len(nomi) != 1:
            raise ValueError(f"Contenuto inatteso in {zpath.name}: {z.namelist()}")
        foglio = pd.read_excel(io.BytesIO(z.read(nomi[0])), sheet_name="DATI SBILANCIAMENTO")
    col_prezzo = next(c for c in foglio.columns if "medio ponderato" in str(c).lower())
    codici = foglio.iloc[:, 0].astype("string").str.replace(r"\.0$", "", regex=True)
    giorno = pd.to_datetime(codici, format="%Y%m%d", errors="coerce")
    ok = giorno.notna()
    prezzo = pd.to_numeric(foglio.loc[ok, col_prezzo], errors="coerce")
    return pd.Series(prezzo.to_numpy(dtype=float), index=pd.DatetimeIndex(giorno[ok]))


def carica_gas_psv() -> pd.Series:
    """Prezzo mensile del gas al PSV (EUR/MWh), media semplice dei giorni gas.

    Fonte: GME, file "Anno termico" del MGP-GAS, colonna "Prezzo medio ponderato":
    media dei prezzi di tutti gli scambi del giorno sui mercati a pronti del gas del
    GME (MGAS), ponderata per i volumi. È un prezzo spot, come il PUN.

    La serie parte da ``INIZIO_PSV``. I giorni senza scambi (8 e 9 ottobre 2016)
    sono esclusi dalla media del mese; se in un mese i giorni con prezzo sono meno
    del 90%, errore.
    """
    inizio = pd.Timestamp(cfg.INIZIO_PSV)
    fine = pd.Timestamp(cfg.FINE) + pd.offsets.MonthEnd(0)
    primo = inizio.year if inizio.month >= 10 else inizio.year - 1     # l'anno termico
    ultimo = fine.year if fine.month >= 10 else fine.year - 1          # inizia a ottobre
    # I file vanno scaricati a mano: le condizioni d'uso del sito GME vietano
    # lo scaricamento automatico.
    attesi = [cfg.GREZZI_GME_GAS / f"Annotermico{a}-{a + 1}.zip" for a in range(primo, ultimo + 1)]
    mancanti = [p.name for p in attesi if not p.exists()]
    if mancanti:
        raise FileNotFoundError(
            f"Mancano in {cfg.GREZZI_GME_GAS}: {', '.join(mancanti)}.\n"
            f"Scarica i file 'Anno Termico' da {cfg.PAGINA_GME_GAS} (vedi dati/README.md)."
        )
    parti = [_psv_giornaliero(p) for p in attesi]
    giornaliero = pd.concat(parti).sort_index().loc[inizio:fine]

    if not giornaliero.index.equals(pd.date_range(inizio, fine, freq="D")):
        raise ValueError("Serie PSV giornaliera con giorni mancanti o duplicati")
    copertura = giornaliero.notna().resample("MS").mean()
    if (copertura < 0.9).any():
        raise ValueError(f"Mesi PSV con pochi giorni di scambio:\n{copertura[copertura < 0.9]}")
    return giornaliero.resample("MS").mean().rename("Gas_PSV")


# ---------------------------------------------------------------------------
# Gas TTF (World Bank) e cambio EUR/USD (FRED): specificazione alternativa
# ---------------------------------------------------------------------------
def _serie_fred(sid: str) -> pd.Series:
    path = _download(FRED_URL.format(sid=sid), cfg.GREZZI / "fred" / f"{sid}.csv")
    s = pd.read_csv(path, index_col=0, parse_dates=True).iloc[:, 0]
    return pd.to_numeric(s, errors="coerce")


def _gas_europa_world_bank(path: Path = cfg.FILE_WORLD_BANK) -> pd.Series:
    """Colonna "Natural gas, Europe" del Pink Sheet mensile (USD/MMBtu)."""
    if not path.exists():
        raise FileNotFoundError(
            f"Manca {path}.\nScarica 'Monthly prices' (CMO-Historical-Data-Monthly.xlsx) "
            f"da {cfg.PAGINA_WORLD_BANK} e salvalo in quel percorso."
        )
    raw = pd.read_excel(path, sheet_name="Monthly Prices", header=None)
    nome = "Natural gas, Europe"
    riga = next(i for i in range(15) if (raw.iloc[i].astype(str).str.strip() == nome).any())
    col = next(j for j in raw.columns if str(raw.iat[riga, j]).strip() == nome)
    unita = str(raw.iat[riga + 1, col]).strip().lower()
    if unita != "($/mmbtu)":
        raise ValueError(f"Unità inattesa per '{nome}': {unita}")
    periodi = raw.iloc[riga + 2 :, 0].astype(str).str.strip()
    mensili = periodi.str.fullmatch(r"\d{4}M\d{2}", na=False)
    date = pd.to_datetime(periodi[mensili].str.replace("M", "-") + "-01")
    valori = pd.to_numeric(raw.iloc[riga + 2 :, col][mensili], errors="coerce")
    return pd.Series(valori.to_numpy(dtype=float), index=date)


def carica_gas_ttf() -> pd.Series:
    """Prezzo mensile del gas TTF in EUR/MWh (vicino al contratto del mese successivo)."""
    usd_mmbtu = _gas_europa_world_bank()
    usd_per_eur = _serie_fred("EXUSEU")
    return (usd_mmbtu / cfg.MWH_PER_MMBTU / usd_per_eur).dropna().rename("Gas_TTF")


# ---------------------------------------------------------------------------
# CO2 EUA (aste primarie EEX)
# ---------------------------------------------------------------------------
def _leggi_report_aste(fonte) -> pd.DataFrame:
    raw = pd.read_excel(fonte, sheet_name=0, header=None)
    riga = next(i for i in range(15) if (raw.iloc[i].astype(str).str.strip() == "Date").any())
    df = raw.iloc[riga + 1 :].copy()
    df.columns = [str(c).strip() for c in raw.iloc[riga]]
    col_prezzo = next(c for c in df.columns if c.startswith("Auction Price"))
    df = df[df["Contract"] == "T3PA"]                          # EUA generali (no aviazione)
    if "Status" in df.columns:
        df = df[df["Status"].astype(str).str.lower() == "successful"]
    out = pd.DataFrame({
        "Date": pd.to_datetime(df["Date"]),
        "Prezzo": pd.to_numeric(df[col_prezzo], errors="coerce"),
    })
    return out.dropna()


def carica_co2_eua() -> pd.Series:
    """Media mensile semplice dei prezzi d'asta EUA (EUR/tCO2)."""
    zpath = _download(
        EEX_ARCHIVE_URL, cfg.GREZZI / "eex" / "eua_auction_report_2012_2025.zip", "Mozilla/5.0"
    )
    aste = []
    with zipfile.ZipFile(zpath) as z:
        for nome in z.namelist():
            anno = re.search(r"report-(\d{4})-data", nome)
            if anno and int(anno.group(1)) >= 2015:
                aste.append(_leggi_report_aste(io.BytesIO(z.read(nome))))
    aste = pd.concat(aste).set_index("Date").sort_index()["Prezzo"]
    return aste.resample("MS").mean().rename("CO2_EUA")


# ---------------------------------------------------------------------------
# Strumenti per la domanda: gradi-giorno (Eurostat) e giorni lavorativi
# ---------------------------------------------------------------------------
def _tabella_eurostat(js: dict) -> pd.DataFrame:
    """Converte la risposta JSON-stat di Eurostat in una tabella lunga."""
    ids, size = js["id"], js["size"]
    etichette = {d: {i: k for k, i in js["dimension"][d]["category"]["index"].items()} for d in ids}
    righe = []
    for pos, valore in js["value"].items():
        resto, coord = int(pos), {}
        for d, n in zip(reversed(ids), reversed(size)):
            coord[d] = etichette[d][resto % n]
            resto //= n
        righe.append({**coord, "valore": valore})
    return pd.DataFrame(righe)


def carica_gradi_giorno() -> pd.DataFrame:
    """Gradi-giorno mensili di riscaldamento (HDD) e raffrescamento (CDD), Italia."""
    path = _download(EUROSTAT_HDD_URL, cfg.GREZZI / "eurostat" / "nrg_chdd_m_IT.json")
    tab = _tabella_eurostat(json.loads(path.read_text(encoding="utf-8")))
    if set(tab["geo"]) != {"IT"} or set(tab["unit"]) != {"NR"}:
        raise ValueError("Risposta Eurostat inattesa (paese o unità)")
    wide = tab.pivot(index="time", columns="indic_nrg", values="valore")
    wide.index = pd.to_datetime(wide.index)
    wide.columns.name = None
    return wide[["HDD", "CDD"]].astype(float)


# Festività nazionali a data fissa (mese, giorno); la Pasquetta è calcolata a parte.
FESTIVITA_FISSE = [(1, 1), (1, 6), (4, 25), (5, 1), (6, 2), (8, 15), (11, 1), (12, 8), (12, 25), (12, 26)]


def giorni_lavorativi(mesi: pd.DatetimeIndex) -> pd.Series:
    """Giorni lavorativi del mese: lunedì-venerdì, escluse le festività nazionali."""
    conteggi = []
    for m in mesi:
        feste = {pd.Timestamp(m.year, mm, gg) for mm, gg in FESTIVITA_FISSE}
        feste.add(pd.Timestamp(easter(m.year)) + pd.Timedelta(days=1))   # Lunedì dell'Angelo
        giorni = pd.date_range(m, m + pd.offsets.MonthEnd(0), freq="D")
        conteggi.append(sum(1 for g in giorni if g.weekday() < 5 and g not in feste))
    return pd.Series(conteggi, index=mesi, name="Giorni_lavorativi")


# ---------------------------------------------------------------------------
# Dataset finale
# ---------------------------------------------------------------------------
def _costo_marginale(gas: pd.Series, co2: pd.Series) -> pd.Series:
    """Costo marginale di combustibile e CO2 di una CCGT (EUR/MWh elettrico)."""
    return gas / cfg.ETA_CCGT + cfg.EF_CCGT * co2


def costruisci_dataset(salva: bool = True) -> pd.DataFrame:
    """Unisce le fonti, calcola le variabili derivate e salva in ``dati/elaborati``.

    Non c'è alcuna imputazione: se manca un mese in una qualsiasi fonte, errore.
    L'unica eccezione dichiarata è il PSV, che parte da ``INIZIO_PSV``: prima di
    quella data ``Gas_PSV`` e ``MC_CCGT_PSV`` sono vuoti.
    """
    df = pd.concat(
        [carica_pun(), carica_ember_italia(), carica_gas_psv(), carica_gas_ttf(),
         carica_co2_eua(), carica_gradi_giorno()],
        axis=1,
        sort=True,
    ).loc[cfg.INIZIO : cfg.FINE]

    mesi_attesi = pd.date_range(cfg.INIZIO, cfg.FINE, freq="MS")
    mancanti = df.isna()
    mancanti.loc[df.index < pd.Timestamp(cfg.INIZIO_PSV), "Gas_PSV"] = False   # vuoto atteso
    if not df.index.equals(mesi_attesi) or mancanti.any().any():
        raise ValueError(f"Dataset incompleto:\n{df.reindex(mesi_attesi).isna().sum()}")

    df["Ore"] = df["Ore"].astype(int)
    df["Giorni_lavorativi"] = giorni_lavorativi(df.index)
    df["VRE"] = df["Solar"] + df["Wind"]
    df["Residual_Load"] = df["Demand"] - df["VRE"]
    df["VRE_Share"] = 100 * df["VRE"] / df["Demand"]
    df["MC_CCGT_PSV"] = _costo_marginale(df["Gas_PSV"], df["CO2_EUA"])
    df["MC_CCGT_TTF"] = _costo_marginale(df["Gas_TTF"], df["CO2_EUA"])
    df = df[COLONNE]
    df.index.name = "Date"

    if salva:
        cfg.ELABORATI.mkdir(parents=True, exist_ok=True)
        df.round(4).to_csv(cfg.ELABORATI / "dataset_mensile.csv")
    return df


def carica_dataset() -> pd.DataFrame:
    """Legge il dataset mensile già elaborato (non servono i dati grezzi)."""
    return pd.read_csv(cfg.ELABORATI / "dataset_mensile.csv", index_col="Date", parse_dates=True)


if __name__ == "__main__":
    d = costruisci_dataset()
    print(f"Dataset salvato: {len(d)} mesi, {d.index.min():%Y-%m} -> {d.index.max():%Y-%m}")
    print(d.describe().round(2).T)
