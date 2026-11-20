"""B. Retroceso en tendencia (SPEC §3).

Todo se evalúa con el cierre del día t; la orden se ejecuta en la apertura de t+1.
"""
from __future__ import annotations

import pandas as pd

from src import indicadores as ind

CLAVE = "B"


def senales(df: pd.DataFrame, p: dict, p_ind: dict) -> pd.DataFrame:
    """Columnas: entrada (bool), salida (bool), atr.

    - entrada_t: cierre_t > SMA(200)_t y RSI(2)_t < 10.
    - salida_t (regla): cierre_t > SMA(5)_t o RSI(2)_t > 70.
    """
    c = df["close"]
    tendencia = ind.sma(c, p_ind["sma_tendencia"])
    r = ind.rsi(c, p["rsi_periodo"])
    return pd.DataFrame({
        "entrada": (c > tendencia) & (r < p["rsi_entrada"]),
        "salida": (c > ind.sma(c, p["sma_salida"])) | (r > p["rsi_salida"]),
        "atr": ind.atr(df["high"], df["low"], c, p_ind["atr"]),
    }, index=df.index)


def stop_inicial(entrada: float, atr: float, p: dict) -> float:
    return entrada - p["stop_atr"] * atr


def stop_dinamico(stop_actual: float, maximo_cierre: float, atr: float, p: dict) -> float:
    return stop_actual  # B no tiene stop dinámico


def sesiones_maximas(p: dict) -> int | None:
    return int(p["sesiones_maximas"])
