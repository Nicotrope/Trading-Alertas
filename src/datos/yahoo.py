"""Fuente de datos Yahoo Finance (yfinance): acciones, ETFs, índices y divisas."""
from __future__ import annotations

import time
from datetime import date, timedelta

import pandas as pd

from .proveedor import DataProvider, ErrorDatos, normalizar, recortar


class YahooProvider(DataProvider):
    nombre = "yahoo"

    def __init__(self, reintentos: int = 3, pausa: float = 2.0):
        self.reintentos = reintentos
        self.pausa = pausa

    def descargar(self, simbolo: str, desde: date, hasta: date) -> pd.DataFrame:
        import yfinance as yf

        ultimo_error: Exception | None = None
        for intento in range(self.reintentos):
            try:
                crudo = yf.Ticker(simbolo).history(
                    start=desde.isoformat(),
                    end=(hasta + timedelta(days=1)).isoformat(),  # 'end' es exclusivo
                    interval="1d",
                    auto_adjust=True,  # OHLC ajustado por dividendos y splits
                    actions=False,
                    raise_errors=True,
                )
                return recortar(normalizar(crudo), desde, hasta)
            except Exception as e:  # yfinance lanza tipos variados
                ultimo_error = e
                time.sleep(self.pausa * (intento + 1))
        raise ErrorDatos(f"{simbolo}: {ultimo_error}")
