# Dati

I dati **non sono distribuiti** con questo repository. Le condizioni d'uso di alcune fonti (GME, EEX) non consentono di ripubblicarli, nemmeno in forma aggregata, senza autorizzazione. Tutte le fonti sono però gratuite e accessibili a chiunque: questa pagina spiega come ricostruire il dataset in pochi minuti.

## Come ricostruire il dataset

1. Scarica a mano i file della tabella qui sotto e salvali nelle cartelle indicate.
2. Esegui dalla cartella principale:

   ```bash
   python -m src.dati
   ```

   Lo script scarica da solo le fonti indicate come "automatico", controlla la completezza di ogni serie e crea `dati/elaborati/dataset_mensile.csv` (119 mesi, gennaio 2016 – novembre 2025).
3. Verifica con `pytest`: i controlli sul dataset confrontano, tra l'altro, le medie annue del PUN con quelle pubblicate dal GME.

## Fonti

| Serie | Fonte | Cosa scaricare | Cartella | Scaricamento |
|---|---|---|---|---|
| PUN orario | [GME, dati storici MGP](https://www.mercatoelettrico.org/it-it/Home/Esiti/Elettricita/MGP/Statistiche/DatiStorici) | file annuali `Anno AAAA.xlsx`, dal 2016 al 2025 (per il 2025 il file orario `_60`) | `dati/grezzi/gme_pun/` | a mano |
| Gas PSV | [GME, dati storici MGP-GAS](https://www.mercatoelettrico.org/it-it/Home/Esiti/Gas/MGP-GAS/Statistiche/DatiStorici) | file `Annotermico AAAA-AAAA.zip`, da 2016-2017 a 2025-2026 | `dati/grezzi/gme_gas/` | a mano |
| Domanda, solare, eolico, idroelettrico | [Ember, Monthly electricity data](https://ember-energy.org/data/monthly-electricity-data/) | export Europa in formato *long*: `europe_monthly_full_release_long_format.csv` | `dati/grezzi/ember/` | a mano |
| Gas TTF | [World Bank, Commodity Markets](https://www.worldbank.org/en/research/commodity-markets) | *Monthly prices*: `CMO-Historical-Data-Monthly.xlsx` | `dati/grezzi/worldbank/` | a mano |
| CO2 (EUA) | [EEX, aste primarie EU ETS](https://www.eex.com/en/markets/environmentals/eu-ets1-eu-ets2-auctions/eu-ets1-auctions) | archivio dei report d'asta 2012-2025 | `dati/grezzi/eex/` | automatico |
| Cambio EUR/USD | [FRED, serie `EXUSEU`](https://fred.stlouisfed.org/series/EXUSEU) | – | `dati/grezzi/fred/` | automatico |
| Gradi-giorno | [Eurostat, tabella `nrg_chdd_m`](https://ec.europa.eu/eurostat/databrowser/view/nrg_chdd_m/default/table) | – | `dati/grezzi/eurostat/` | automatico |

I file GME vanno scaricati a mano perché le condizioni d'uso del sito vietano lo scaricamento automatico.

## Condizioni d'uso

| Fonte | Condizioni | Riuso |
|---|---|---|
| Ember | CC BY 4.0 | libero, con citazione |
| World Bank | CC BY 4.0 | libero, con citazione |
| Eurostat | riuso autorizzato con citazione della fonte | libero, con citazione |
| FRED (Board of Governors of the Federal Reserve System) | pubblico dominio, citazione richiesta | libero, con citazione |
| GME | uso personale e informativo, con citazione "Fonte: Gestore dei Mercati Energetici SpA"; pubblicazione e ridistribuzione solo con permesso scritto | solo uso proprio |
| EEX | contenuti protetti; copia e ridistribuzione solo con consenso scritto | solo uso proprio |

Grafici e tabelle di risultati nel notebook e nel README sono elaborazioni dell'autore e riportano la fonte dei dati.

## Versioni usate per i risultati pubblicati

| Fonte | Versione |
|---|---|
| GME (PUN) | esiti MGP gennaio 2016 – novembre 2025 |
| Ember | file scaricato il 26 gennaio 2026 |
| World Bank | Pink Sheet aggiornato al 3 novembre 2026 |
| Eurostat | tabella aggiornata all'8 maggio 2026 |
| GME (gas), FRED, EEX | scaricati il 12 novembre 2026 |

Ember e World Bank possono rivedere i dati storici: con versioni diverse i risultati possono cambiare leggermente.

## Colonne del dataset

| Colonna | Descrizione | Unità |
|---|---|---|
| `PUN` | Prezzo Unico Nazionale, media mensile dei prezzi orari | €/MWh |
| `Ore` | ore del mese | h |
| `Demand` | domanda elettrica | TWh |
| `Solar`, `Wind`, `Hydro` | generazione solare, eolica, idroelettrica | TWh |
| `Gas_PSV` | gas al PSV, prezzo spot (da ottobre 2016) | €/MWh |
| `Gas_TTF` | gas al TTF | €/MWh |
| `CO2_EUA` | permessi di emissione, prezzo d'asta | €/tCO2 |
| `HDD`, `CDD` | gradi-giorno di riscaldamento e raffrescamento | numero |
| `Giorni_lavorativi` | lunedì-venerdì, escluse le festività nazionali | giorni |
| `VRE`, `Residual_Load`, `VRE_Share` | solare + eolico; domanda − VRE; VRE / domanda | TWh, TWh, % |
| `MC_CCGT_PSV`, `MC_CCGT_TTF` | costo marginale di una centrale a ciclo combinato | €/MWh |
