"""A. Ruptura en tendencia (SPEC §3).

Todo se evalúa con el cierre del día t; la orden se ejecuta en la apertura de t+1.
"""
from __future__ import annotations

import pandas as pd

from src import indicadores as ind

CLAVE = "A"


def senales(df: pd.DataFrame, p: dict, p_ind: dict) -> pd.DataFrame:
    """Columnas: entrada (bool), salida (bool), atr, sma (tendencia).

    - entrada_t: cierre_t > SMA(200)_t y cierre_t >= máximo de los 20 cierres anteriores.
    - salida_t (regla): cierre_t < mínimo de los 10 cierres anteriores.
    """
    c = df["close"]
    tendencia = ind.sma(c, p_ind["sma_tendencia"])
    maximo = ind.maximo_previo(c, p["maximo_cierres"])
    minimo = ind.minimo_previo(c, p["salida_minimo"])
    return pd.DataFrame({
        "entrada": (c > tendencia) & (c >= maximo),
        "salida": c < minimo,
        "atr": ind.atr(df["high"], df["low"], c, p_ind["atr"]),
    }, index=df.index)


def stop_inicial(entrada: float, atr: float, p: dict) -> float:
    return entrada - p["stop_atr"] * atr


def stop_dinamico(stop_actual: float, maximo_cierre: float, atr: float, p: dict) -> float:
    """Máximo cierre desde la entrada − 3 × ATR; el stop solo sube."""
    return max(stop_actual, maximo_cierre - p["stop_dinamico_atr"] * atr)


def sesiones_maximas(p: dict) -> int | None:
    return None
