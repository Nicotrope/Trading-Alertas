"""Fuente de datos cripto vía ccxt (exchange público, por defecto Kraken)."""
from __future__ import annotations

import time
from datetime import date, datetime, timezone

import pandas as pd

from .proveedor import DataProvider, ErrorDatos, normalizar, recortar, vacio

UN_DIA_MS = 86_400_000


class CcxtProvider(DataProvider):
    """Velas diarias de un exchange público. Solo lectura: nunca envía órdenes.

    Las velas diarias de Kraken empiezan a las 00:00 UTC; la fecha de la vela es
    ese día UTC. La vela del día en curso sigue abierta: la capa de caché la
    descarta recortando a la última fecha cerrada.
    """

    def __init__(self, exchange: str = "kraken", limite: int = 720, reintentos: int = 3):
        self.nombre = exchange
        self.exchange_id = exchange
        self.limite = limite
        self.reintentos = reintentos
        self._ex = None

    def _exchange(self):
        if self._ex is None:
            import ccxt

            # requests_trust_env: respeta HTTPS_PROXY y REQUESTS_CA_BUNDLE del sistema
            # (sin esto ccxt ignora el proxy/certificados configurados y falla).
            self._ex = getattr(ccxt, self.exchange_id)({"enableRateLimit": True, "requests_trust_env": True})
        return self._ex

    def _pedir(self, simbolo: str, since_ms: int) -> list[list]:
        ultimo_error: Exception | None = None
        for intento in range(self.reintentos):
            try:
                return self._exchange().fetch_ohlcv(simbolo, "1d", since=since_ms, limit=self.limite)
            except Exception as e:
                ultimo_error = e
                time.sleep(2 * (intento + 1))
        raise ErrorDatos(f"{simbolo}: {ultimo_error}")

    def descargar(self, simbolo: str, desde: date, hasta: date) -> pd.DataFrame:
        since = int(datetime(desde.year, desde.month, desde.day, tzinfo=timezone.utc).timestamp() * 1000)
        fin = int(datetime(hasta.year, hasta.month, hasta.day, tzinfo=timezone.utc).timestamp() * 1000)
        filas: list[list] = []
        while since <= fin:
            lote = self._pedir(simbolo, since)
            if not lote:
                break
            filas.extend(lote)
            siguiente = lote[-1][0] + UN_DIA_MS
            if siguiente <= since:
                break
            since = siguiente
            if len(lote) < 2:
                break
        if not filas:
            return vacio()
        df = pd.DataFrame(filas, columns=["ts", "open", "high", "low", "close", "volume"])
        df.index = pd.to_datetime(df.pop("ts"), unit="ms", utc=True)
        return recortar(normalizar(df), desde, hasta)
