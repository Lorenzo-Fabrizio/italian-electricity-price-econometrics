"""Stile comune dei grafici: una sola tavolozza, verificata per i daltonici."""

from __future__ import annotations

import matplotlib.pyplot as plt

from . import config as cfg

# Colori per ruolo: lo stesso significato ha lo stesso colore in tutti i grafici.
BLU = "#2a78d6"        # serie osservata / stima principale
ARANCIO = "#eb6834"    # scenario alternativo / serie di confronto
VERDE = "#1baf7a"      # effetto delle rinnovabili
GIALLO = "#eda100"     # solare
AZZURRO = "#86b6ef"    # idroelettrico (tonalità chiara del blu)
TESTO = "#0b0b0b"
TESTO_SECONDARIO = "#52514e"
GRIGIO = "#898781"
GRIGLIA = "#e1e0d9"
ASSE = "#c3c2b7"
SFONDO = "#fcfcfb"


def imposta_stile() -> None:
    """Applica lo stile a tutti i grafici matplotlib della sessione."""
    plt.rcParams.update({
        "figure.figsize": (12, 5.5),
        "figure.facecolor": SFONDO,
        "axes.facecolor": SFONDO,
        "savefig.facecolor": SFONDO,
        "savefig.dpi": 160,
        "savefig.bbox": "tight",
        "font.size": 11,
        "text.color": TESTO,
        "axes.titlesize": 13,
        "axes.titleweight": "bold",
        "axes.titlelocation": "left",
        "axes.titlepad": 12,
        "axes.labelcolor": TESTO_SECONDARIO,
        "axes.edgecolor": ASSE,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.spines.left": False,
        "axes.grid": True,
        "axes.grid.axis": "y",
        "axes.axisbelow": True,
        "grid.color": GRIGLIA,
        "grid.linewidth": 0.8,
        "xtick.color": GRIGIO,
        "ytick.color": GRIGIO,
        "xtick.labelcolor": TESTO_SECONDARIO,
        "ytick.labelcolor": TESTO_SECONDARIO,
        "ytick.left": False,
        "lines.linewidth": 2,
        "legend.frameon": False,
    })


def fonte(fig, testo: str) -> None:
    """Scrive la fonte dei dati in basso a sinistra."""
    fig.text(0.01, -0.02, f"Fonte: {testo}", ha="left", va="top", fontsize=9, color=GRIGIO)


def salva(fig, nome: str) -> None:
    """Salva il grafico in ``figure/`` (immagini usate dal README)."""
    cfg.FIGURE.mkdir(exist_ok=True)
    fig.savefig(cfg.FIGURE / nome)
