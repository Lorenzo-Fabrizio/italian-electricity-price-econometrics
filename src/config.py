"""Percorsi e parametri dell'analisi, definiti in un unico punto."""

from pathlib import Path

# --- Percorsi -------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[1]
DATI = ROOT / "dati"
ELABORATI = DATI / "elaborati"    # dataset mensile pulito (versionato)
FIGURE = ROOT / "figure"

# Dati grezzi (non versionati, vedi README): una sottocartella per fonte.
GREZZI = DATI / "grezzi"
GREZZI_GME_PUN = GREZZI / "gme_pun"       # da scaricare a mano: "Anno AAAA*.xlsx"
GREZZI_GME_GAS = GREZZI / "gme_gas"       # da scaricare a mano: "Annotermico*.zip"
PAGINA_GME_GAS = (
    "https://www.mercatoelettrico.org/it-it/Home/Esiti/Gas/MGP-GAS/Statistiche/DatiStorici"
)
FILE_EMBER = GREZZI / "ember" / "europe_monthly_full_release_long_format.csv"   # a mano
FILE_WORLD_BANK = GREZZI / "worldbank" / "CMO-Historical-Data-Monthly.xlsx"     # a mano
PAGINA_WORLD_BANK = "https://www.worldbank.org/en/research/commodity-markets"

# --- Periodo --------------------------------------------------------------
INIZIO = "2016-01-01"
FINE = "2025-11-01"
# Prezzo del gas italiano (PSV, mercati GME): prima di ottobre 2016 il MGP-GAS non
# ha scambi. Il modello principale usa quindi le variazioni da novembre 2016.
INIZIO_PSV = "2016-10-01"

# --- Parametri tecnici della centrale CCGT di riferimento ------------------
# Sono ipotesi, non stime. ETA incide solo sul livello di MC_CCGT (si annulla nelle
# log-differenze); il notebook (sezione 10) verifica il peso relativo di gas e CO2.
ETA_CCGT = 0.55        # rendimento elettrico
EF_CCGT = 0.37         # tCO2 per MWh elettrico (circa 0,202 tCO2/MWh di gas / 0,55)

# --- Conversioni ----------------------------------------------------------
MWH_PER_MMBTU = 0.293071   # 1 MMBtu = 0,293071 MWh

# --- Stima ----------------------------------------------------------------
# Ritardi Newey-West: regola floor(4 * (T/100)^(2/9)) con T = 109 osservazioni
# (novembre 2016 - novembre 2025) -> 4. Con T = 118 (modello TTF) il risultato è uguale.
HAC_LAGS = 4
