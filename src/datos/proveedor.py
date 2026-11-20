"""Interfaz común de las fuentes de datos.

Cualquier fuente (yfinance, ccxt, una fuente de pago futura) implementa
`DataProvider.descargar` y devuelve velas diarias con el formato normalizado:

- índice `DatetimeIndex` llamado ``fecha``, sin zona horaria, a medianoche,
  ordenado y sin duplicados (una fila = un día de cotización);
- columnas ``open, high, low, close, volume`` en float, precios ajustados por
  dividendos y splits cuando la fuente lo permite.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date

import pandas as pd

COLUMNAS = ["open", "high", "low", "close", "volume"]


class ErrorDatos(Exception):
    """La fuente no pudo devolver datos para un activo."""


class DataProvider(ABC):
    nombre: str = "base"

    @abstractmethod
    def descargar(self, simbolo: str, desde: date, hasta: date) -> pd.DataFrame:
        """Velas diarias de `simbolo` con fecha en [desde, hasta], ambos incluidos."""


def normalizar(df: pd.DataFrame) -> pd.DataFrame:
    """Lleva un DataFrame de velas al formato común."""
    if df is None or df.empty:
        return vacio()
    df = df.rename(columns=str.lower)
    faltan = [c for c in COLUMNAS if c not in df.columns]
    if faltan:
        raise ErrorDatos(f"faltan columnas {faltan}")
    df = df[COLUMNAS].astype(float)
    idx = pd.DatetimeIndex(df.index)
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    df.index = idx.normalize()
    df.index.name = "fecha"
    df = df[~df.index.duplicated(keep="last")].sort_index()
    return df


def vacio() -> pd.DataFrame:
    df = pd.DataFrame(columns=COLUMNAS, dtype=float)
    df.index = pd.DatetimeIndex([], name="fecha")
    return df


def recortar(df: pd.DataFrame, desde: date | None, hasta: date | None) -> pd.DataFrame:
    if desde is not None:
        df = df[df.index >= pd.Timestamp(desde)]
    if hasta is not None:
        df = df[df.index <= pd.Timestamp(hasta)]
    return df
