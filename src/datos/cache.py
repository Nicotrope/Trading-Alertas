"""Caché local en Parquet: un archivo por activo, solo se piden las velas nuevas."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from .proveedor import COLUMNAS, DataProvider, recortar


def nombre_archivo(simbolo: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", simbolo) + ".parquet"


@dataclass
class ResultadoActualizacion:
    simbolo: str
    datos: pd.DataFrame
    accion: str          # "completa", "incremental", "sin_cambios", "redescarga_ajuste"
    nuevas: int
    detalle: str = ""


class CacheParquet:
    """Guarda velas con una columna extra ``fuente`` (de qué proveedor vino cada vela)."""

    def __init__(self, carpeta: Path):
        self.carpeta = Path(carpeta)

    def ruta(self, simbolo: str) -> Path:
        return self.carpeta / nombre_archivo(simbolo)

    def leer(self, simbolo: str) -> pd.DataFrame | None:
        p = self.ruta(simbolo)
        if not p.exists():
            return None
        df = pd.read_parquet(p)
        df.index = pd.DatetimeIndex(df.index, name="fecha")
        return df

    def guardar(self, simbolo: str, df: pd.DataFrame) -> None:
        self.carpeta.mkdir(parents=True, exist_ok=True)
        tmp = self.ruta(simbolo).with_suffix(".tmp")
        df.to_parquet(tmp)
        tmp.replace(self.ruta(simbolo))


def _con_fuente(df: pd.DataFrame, fuente: str) -> pd.DataFrame:
    df = df[COLUMNAS].copy()
    df["fuente"] = fuente
    return df


def actualizar(
    cache: CacheParquet,
    proveedor: DataProvider,
    simbolo: str,
    hasta: date,
    desde_inicial: date,
    dias_solape: int = 10,
    tolerancia_ajuste: float = 0.001,
    respaldo: DataProvider | None = None,
    simbolo_respaldo: str | None = None,
) -> ResultadoActualizacion:
    """Trae las velas hasta `hasta` (última vela cerrada) y actualiza la caché.

    - Sin caché: descarga desde `desde_inicial`. Si el proveedor no llega tan atrás
      y hay `respaldo`, la parte antigua se completa con el respaldo.
    - Con caché: vuelve a pedir los últimos `dias_solape` días. Si los cierres solapados
      cambian más que `tolerancia_ajuste` (dividendo/split reajustó la serie), redescarga todo.
    - Nunca guarda velas posteriores a `hasta`.
    """
    previo = cache.leer(simbolo)

    def completa(motivo: str) -> ResultadoActualizacion:
        nuevo = _con_fuente(proveedor.descargar(simbolo, desde_inicial, hasta), proveedor.nombre)
        detalle = ""
        if respaldo is not None and simbolo_respaldo:
            primera = nuevo.index.min() if len(nuevo) else pd.Timestamp(hasta) + pd.Timedelta(days=1)
            if primera > pd.Timestamp(desde_inicial) + pd.Timedelta(days=7):
                antiguo = respaldo.descargar(simbolo_respaldo, desde_inicial, (primera - pd.Timedelta(days=1)).date())
                antiguo = _con_fuente(antiguo, f"{respaldo.nombre}:{simbolo_respaldo}")
                nuevo = pd.concat([antiguo[antiguo.index < primera], nuevo]).sort_index()
                detalle = f"{len(antiguo)} velas antiguas de {respaldo.nombre}"
        nuevo = recortar(nuevo, None, hasta)
        cache.guardar(simbolo, nuevo)
        return ResultadoActualizacion(simbolo, nuevo, motivo, len(nuevo), detalle)

    if previo is None or previo.empty:
        return completa("completa")

    previo = recortar(previo, None, hasta)
    ultima = previo.index.max().date()
    desde = ultima - timedelta(days=dias_solape)
    reciente = proveedor.descargar(simbolo, desde, hasta)
    if reciente.empty:
        return ResultadoActualizacion(simbolo, previo, "sin_cambios", 0, "la fuente no devolvió velas recientes")

    # ¿Ha cambiado el ajuste histórico? Solo se comparan velas de la misma fuente.
    comun = previo.index.intersection(reciente.index)
    comun = comun[previo.loc[comun, "fuente"] == proveedor.nombre]
    if len(comun):
        dif = (reciente.loc[comun, "close"] / previo.loc[comun, "close"] - 1).abs().max()
        # En cripto (con respaldo) no hay ajustes por dividendos: una diferencia es una
        # corrección del exchange y basta con sobrescribir las velas recientes.
        if dif > tolerancia_ajuste and respaldo is None:
            return completa("redescarga_ajuste")

    nuevas = reciente[~reciente.index.isin(previo.index)]
    combinado = pd.concat([previo[previo.index < reciente.index.min()], _con_fuente(reciente, proveedor.nombre)])
    combinado = recortar(combinado.sort_index(), None, hasta)
    cache.guardar(simbolo, combinado)
    accion = "incremental" if len(nuevas) else "sin_cambios"
    return ResultadoActualizacion(simbolo, combinado, accion, len(nuevas))
