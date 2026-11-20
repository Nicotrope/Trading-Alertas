"""Indicadores técnicos, implementación propia.

Regla común: el valor en la fecha t solo usa datos hasta t (incluido). Nada mira
al futuro. Los tests de tests/test_sin_futuro.py lo comprueban para cada función.

Cuando no hay historia suficiente el valor es NaN (nunca se rellena hacia atrás).
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _comprobar(serie: pd.Series, n: int) -> None:
    if n < 1:
        raise ValueError("el periodo debe ser >= 1")
    if serie.isna().any():
        raise ValueError("la serie contiene NaN: valida los datos antes de calcular indicadores")


def sma(close: pd.Series, n: int) -> pd.Series:
    """Media simple de los últimos n cierres (incluido el de t)."""
    _comprobar(close, n)
    return close.rolling(n, min_periods=n).mean()


def _wilder(valores: np.ndarray, n: int, inicio: int) -> np.ndarray:
    """Suavizado de Wilder. La primera media es la media simple de valores[inicio:inicio+n];
    después m_t = (m_{t-1} * (n - 1) + x_t) / n."""
    out = np.full(len(valores), np.nan)
    primera = inicio + n - 1
    if primera >= len(valores):
        return out
    out[primera] = valores[inicio:primera + 1].mean()
    for t in range(primera + 1, len(valores)):
        out[t] = (out[t - 1] * (n - 1) + valores[t]) / n
    return out


def rango_verdadero(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    """TR_t = max(H_t - L_t, |H_t - C_{t-1}|, |L_t - C_{t-1}|). En la primera vela, H - L."""
    prev = close.shift(1)
    tr = pd.concat([high - low, (high - prev).abs(), (low - prev).abs()], axis=1).max(axis=1)
    tr.iloc[:1] = (high - low).iloc[:1]
    return tr


def atr(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 14) -> pd.Series:
    """Average True Range de Wilder. Primer valor en la vela n (índice n-1): media de los
    primeros n rangos verdaderos."""
    for s in (high, low, close):
        _comprobar(s, n)
    tr = rango_verdadero(high, low, close)
    return pd.Series(_wilder(tr.to_numpy(float), n, 0), index=close.index, name=f"atr{n}")


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    """RSI de Wilder. Las variaciones empiezan en la segunda vela, así que el primer valor
    está en el índice n. Sin pérdidas → 100; sin movimiento → 50."""
    _comprobar(close, n)
    d = close.diff().to_numpy(float)
    subidas = np.where(d > 0, d, 0.0)
    bajadas = np.where(d < 0, -d, 0.0)
    ms = _wilder(subidas, n, 1)
    mb = _wilder(bajadas, n, 1)
    with np.errstate(divide="ignore", invalid="ignore"):
        valor = 100 - 100 / (1 + ms / mb)
    valor = np.where((mb == 0) & (ms > 0), 100.0, valor)
    valor = np.where((mb == 0) & (ms == 0), 50.0, valor)
    valor[np.isnan(ms)] = np.nan
    return pd.Series(valor, index=close.index, name=f"rsi{n}")


def maximo_previo(serie: pd.Series, n: int) -> pd.Series:
    """Máximo de los n valores ANTERIORES a t (sin incluir t).
    Uso: ruptura = cierre_t >= maximo_previo(cierre, 20)_t."""
    _comprobar(serie, n)
    return serie.shift(1).rolling(n, min_periods=n).max()


def minimo_previo(serie: pd.Series, n: int) -> pd.Series:
    """Mínimo de los n valores ANTERIORES a t (sin incluir t)."""
    _comprobar(serie, n)
    return serie.shift(1).rolling(n, min_periods=n).min()


def rentabilidad(close: pd.Series, n: int) -> pd.Series:
    """Rentabilidad de las últimas n sesiones: C_t / C_{t-n} - 1 (momentum relativo)."""
    _comprobar(close, n)
    return close / close.shift(n) - 1


def tabla_indicadores(df: pd.DataFrame, estrategias: dict) -> pd.DataFrame:
    """Todos los indicadores que usan las estrategias, con los parámetros de estrategias.yaml."""
    p_ind, p_a, p_b = estrategias["indicadores"], estrategias["ruptura"], estrategias["retroceso"]
    c = df["close"]
    out = df[["open", "high", "low", "close"]].copy()
    out[f"sma{p_ind['sma_tendencia']}"] = sma(c, p_ind["sma_tendencia"])
    out[f"sma{p_b['sma_salida']}"] = sma(c, p_b["sma_salida"])
    out[f"atr{p_ind['atr']}"] = atr(df["high"], df["low"], c, p_ind["atr"])
    out[f"rsi{p_b['rsi_periodo']}"] = rsi(c, p_b["rsi_periodo"])
    out[f"max{p_a['maximo_cierres']}"] = maximo_previo(c, p_a["maximo_cierres"])
    out[f"min{p_a['salida_minimo']}"] = minimo_previo(c, p_a["salida_minimo"])
    out[f"mom{p_ind['momentum_sesiones']}"] = rentabilidad(c, p_ind["momentum_sesiones"])
    return out
