"""Explicaciones en palabras simples para el email (solo texto informativo).

Nada de aquí crea ni cambia señales: las compras y ventas las deciden las reglas
de src/estrategias. Este módulo solo describe lo que ha pasado con el precio.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from src import indicadores as ind


@dataclass
class Foto:
    """Situación de un activo al último cierre."""
    simbolo: str
    cierre: float
    var_1: float          # cambio del último día
    var_5: float          # cambio en 5 sesiones
    var_20: float         # cambio en 20 sesiones
    desde_maximo: float   # distancia al máximo de los últimos 60 cierres (negativa)
    sobre_sma: float      # distancia a la media de 200 (positiva = por encima)
    rsi2: float
    maximo20: float       # máximo de los 20 cierres anteriores
    dias_cayendo: int     # sesiones seguidas cerrando a la baja


def foto(simbolo: str, velas: pd.DataFrame, p_ind: dict, p_a: dict, p_b: dict) -> Foto | None:
    c = velas["close"]
    if len(c) < max(p_ind["sma_tendencia"], 61):
        return None
    sma = ind.sma(c, p_ind["sma_tendencia"]).iloc[-1]
    baja = 0
    for d in c.diff().iloc[::-1].iloc[:-1]:
        if d < 0:
            baja += 1
        else:
            break
    return Foto(
        simbolo=simbolo,
        cierre=float(c.iloc[-1]),
        var_1=float(c.iloc[-1] / c.iloc[-2] - 1),
        var_5=float(c.iloc[-1] / c.iloc[-6] - 1),
        var_20=float(c.iloc[-1] / c.iloc[-21] - 1),
        desde_maximo=float(c.iloc[-1] / c.iloc[-60:].max() - 1),
        sobre_sma=float(c.iloc[-1] / sma - 1),
        rsi2=float(ind.rsi(c, p_b["rsi_periodo"]).iloc[-1]),
        maximo20=float(ind.maximo_previo(c, p_a["maximo_cierres"]).iloc[-1]),
        dias_cayendo=baja,
    )


def p(v: float) -> str:
    if abs(v) < 0.001:
        return "menos de un 0,1%"
    return "un " + (f"{abs(v):.0%}" if abs(v) >= 0.1 else f"{abs(v):.1%}".replace(".", ","))


def tendencia(f: Foto) -> str:
    if f.sobre_sma >= 0:
        return f"sigue {p(f.sobre_sma)} por encima de su media de 200 días (tendencia de fondo alcista)"
    return f"está {p(f.sobre_sma)} por debajo de su media de 200 días (tendencia de fondo bajista)"


def por_que_compra(f: Foto, estrategia: str) -> str:
    """Una frase con lo que ha hecho el precio y por qué encaja en la regla."""
    partes = []
    if "B" in estrategia:
        dias = f" en {f.dias_cayendo} sesiones seguidas" if f.dias_cayendo >= 2 else " en la última sesión"
        caida = f.var_5 if f.var_5 < 0 else f.var_1
        partes.append(f"Ha caído {p(caida)}{dias}, pero {tendencia(f)}: es una caída corta dentro de una subida, "
                      "que suele rebotar en pocos días")
    if "A" in estrategia:
        partes.append(f"Ha cerrado en su máximo de las últimas 4 semanas (sube {p(f.var_20)} en 20 sesiones) y "
                      f"{tendencia(f)}: es una ruptura, el precio tiene fuerza")
    return ". ".join(partes) + "."


@dataclass
class Vigilar:
    simbolo: str
    nombre: str
    que_paso: str
    por_que_no: str
    orden: float


def para_vigilar(
    fotos: dict[str, Foto],
    nombres: dict[str, str],
    grupos: dict[str, str],
    regimen: dict[str, bool],
    excluir: set[str],
    p_b: dict,
    caida_min: float = 0.10,
    cerca_maximo: float = 0.02,
    maximo: int = 8,
    descartes: dict[str, str] | None = None,
) -> list[Vigilar]:
    """Activos con movimientos llamativos que NO son señal hoy, con el motivo en palabras simples."""
    caidas: list[Vigilar] = []
    rupturas: list[Vigilar] = []
    for s, f in fotos.items():
        if s in excluir:
            continue
        nombre = nombres.get(s, s)
        reg_ok = regimen.get(grupos.get(s, ""), True)
        motivos_reg = "" if reg_ok else " Además, su mercado está en tendencia bajista y el sistema no compra en ese grupo."
        # Caídas fuertes
        caida = min(f.var_5, f.desde_maximo)
        if caida <= -caida_min:
            if f.var_5 <= -caida_min:
                que = f"Ha caído {p(f.var_5)} en 5 sesiones ({p(f.desde_maximo)} desde su máximo de 3 meses)."
            else:
                que = f"Está {p(f.desde_maximo)} por debajo de su máximo de 3 meses."
            if descartes and s in descartes:
                from src.riesgo import EXPLICACION

                no = f"Cumple la regla de compra, pero hoy no se compra: {EXPLICACION.get(descartes[s], descartes[s])}."
            elif f.sobre_sma < 0:
                no = ("No es señal: " + tendencia(f) + ". Comprar caídas solo funciona cuando la tendencia de fondo "
                      "es alcista; aquí podría seguir bajando.")
            elif f.rsi2 >= p_b["rsi_entrada"]:
                no = (f"No es señal todavía: {tendencia(f)}, pero la caída de los últimos días no es lo bastante "
                      f"brusca (RSI(2) = {f.rsi2:.0f}; la regla pide menos de {p_b['rsi_entrada']}).")
            else:
                no = "No es señal hoy: su mercado está en tendencia bajista." if not reg_ok else "No es señal hoy."
                motivos_reg = ""
            caidas.append(Vigilar(s, nombre, que, no + motivos_reg, orden=caida))
            continue
        # Casi en ruptura
        if f.sobre_sma > 0 and np.isfinite(f.maximo20) and 0 < f.maximo20 / f.cierre - 1 <= cerca_maximo:
            que = f"Está a {p(f.maximo20 / f.cierre - 1)} de su máximo de 4 semanas y {tendencia(f)}."
            no = "No es señal todavía: tiene que cerrar por encima de ese máximo."
            rupturas.append(Vigilar(s, nombre, que, no + motivos_reg, orden=f.maximo20 / f.cierre - 1))
    caidas.sort(key=lambda v: v.orden)
    rupturas.sort(key=lambda v: v.orden)
    n_rup = min(len(rupturas), max(maximo // 3, maximo - len(caidas)))
    return caidas[: maximo - n_rup] + rupturas[:n_rup]
