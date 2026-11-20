"""Validación de velas tras cada descarga: huecos, precios a cero, saltos, desfase."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np
import pandas as pd

from .proveedor import COLUMNAS

ERROR = "error"   # el activo se excluye ese día
AVISO = "aviso"   # se informa, pero el activo sigue siendo apto


@dataclass
class Incidencia:
    severidad: str
    tipo: str
    detalle: str
    fecha: date | None = None

    def __str__(self) -> str:
        f = f" {self.fecha}" if self.fecha else ""
        return f"[{self.severidad}] {self.tipo}{f}: {self.detalle}"


@dataclass
class ResultadoValidacion:
    simbolo: str
    incidencias: list[Incidencia] = field(default_factory=list)

    @property
    def apto(self) -> bool:
        return not any(i.severidad == ERROR for i in self.incidencias)

    @property
    def errores(self) -> list[Incidencia]:
        return [i for i in self.incidencias if i.severidad == ERROR]

    @property
    def avisos(self) -> list[Incidencia]:
        return [i for i in self.incidencias if i.severidad == AVISO]


def validar(
    simbolo: str,
    df: pd.DataFrame,
    fecha_esperada: date,
    params: dict,
    diario: bool = False,
) -> ResultadoValidacion:
    """Valida las velas de un activo.

    `fecha_esperada` es la última vela que debería estar cerrada (ver calendario).
    `diario=True` para activos que cotizan todos los días (cripto).
    Los problemas antiguos (fuera de `ventana_exclusion_dias`) quedan como aviso;
    los recientes son error y excluyen el activo.
    """
    r = ResultadoValidacion(simbolo)
    add = r.incidencias.append

    if df is None or df.empty:
        add(Incidencia(ERROR, "sin_datos", "la fuente no devolvió velas"))
        return r
    faltan = [c for c in COLUMNAS if c not in df.columns]
    if faltan:
        add(Incidencia(ERROR, "columnas", f"faltan {faltan}"))
        return r
    if df.index.has_duplicates:
        add(Incidencia(ERROR, "duplicados", f"{int(df.index.duplicated().sum())} fechas repetidas"))
    if not df.index.is_monotonic_increasing:
        add(Incidencia(ERROR, "orden", "fechas desordenadas"))
        return r

    corte_reciente = pd.Timestamp(fecha_esperada) - pd.Timedelta(days=params["ventana_exclusion_dias"])

    def sev(ts: pd.Timestamp) -> str:
        return ERROR if ts > corte_reciente else AVISO

    def registrar(mascara: pd.Series, tipo: str, texto) -> None:
        for ts in mascara[mascara].index:
            add(Incidencia(sev(ts), tipo, texto(ts), ts.date()))

    precios = df[["open", "high", "low", "close"]]

    # Valores ausentes
    registrar(precios.isna().any(axis=1), "nan", lambda ts: "precio ausente")

    # Precios a cero o negativos
    registrar((precios <= 0).any(axis=1), "precio_cero", lambda ts: f"cierre {df.at[ts, 'close']}")

    # Vela incoherente: máximo por debajo de apertura/cierre o mínimo por encima (tolerancia 0,5 %)
    tol = 0.005
    incoh = (df["high"] * (1 + tol) < df[["open", "close"]].max(axis=1)) | (
        df["low"] * (1 - tol) > df[["open", "close"]].min(axis=1)
    )
    registrar(incoh, "vela_incoherente", lambda ts: "high/low no contienen open/close")

    # Saltos de más del X % de cierre a cierre
    cambio = df["close"].pct_change().abs()
    saltos = cambio > params["salto_maximo"]
    registrar(saltos, "salto", lambda ts: f"cierre cambia {cambio[ts]:.0%} en un día")

    # Huecos entre velas consecutivas
    fechas = df.index
    if len(fechas) > 1:
        if diario:
            dist = np.diff(fechas.values).astype("timedelta64[D]").astype(int) - 1
            limite = params["hueco_maximo_dias_cripto"]
            unidad = "días"
        else:
            dist = np.busday_count(fechas[:-1].values.astype("datetime64[D]"),
                                   fechas[1:].values.astype("datetime64[D]")) - 1
            limite = params["hueco_maximo_dias_habiles"]
            unidad = "días hábiles"
        for i in np.where(dist > limite)[0]:
            ts = fechas[i + 1]
            add(Incidencia(sev(ts), "hueco", f"{int(dist[i])} {unidad} sin velas antes de esta fecha", ts.date()))

    # Velas posteriores a la última cerrada (no debería ocurrir tras el recorte)
    futuras = fechas[fechas > pd.Timestamp(fecha_esperada)]
    if len(futuras):
        add(Incidencia(ERROR, "vela_futura", f"{len(futuras)} velas posteriores a {fecha_esperada}"))

    # Desfase: la última vela es demasiado antigua
    ultima = fechas[fechas <= pd.Timestamp(fecha_esperada)].max() if len(fechas) else None
    if ultima is not None and pd.notna(ultima):
        if diario:
            retraso = (pd.Timestamp(fecha_esperada) - ultima).days
        else:
            retraso = int(np.busday_count(ultima.date(), fecha_esperada))
        if retraso > params["dias_sin_actualizar_max"]:
            add(Incidencia(ERROR, "desfasado", f"última vela {ultima.date()}, se esperaba {fecha_esperada}"))
        elif retraso > 0:
            add(Incidencia(AVISO, "sin_ultima_vela",
                           f"última vela {ultima.date()}, se esperaba {fecha_esperada} (¿festivo?)"))

    # Historia mínima
    if len(df) < params["velas_minimas"]:
        add(Incidencia(ERROR, "historia_corta", f"{len(df)} velas (< {params['velas_minimas']})"))

    return r
