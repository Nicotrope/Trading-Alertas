"""Tamaño de posición y límites de cartera (SPEC §4). Todo en EUR.

Lo usan tanto el backtest como (en fase 3) el sistema diario.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

# Motivos de descarte (aparecen en el email y en el informe del backtest)
SIN_HUECO = "sin hueco"
LIMITE_CRIPTO = "límite cripto"
LIMITE_SECTOR = "límite sector"
BAJO_MINIMO = "por debajo del mínimo"
SIN_LIQUIDEZ = "sin liquidez"
FRENO = "freno por caída"

# Los mismos motivos, explicados para el email
EXPLICACION = {
    SIN_HUECO: "ya hay 8 posiciones abiertas, el máximo",
    LIMITE_CRIPTO: "ya hay un 20 % de la cuenta en cripto, el máximo",
    LIMITE_SECTOR: "ya hay 2 posiciones en ese sector, el máximo",
    BAJO_MINIMO: "la compra saldría de menos de 500 € y las comisiones pesarían demasiado",
    SIN_LIQUIDEZ: "no queda dinero libre suficiente",
    FRENO: "las compras están en pausa por el freno de caída",
}


@dataclass
class Propuesta:
    unidades: float
    importe_eur: float
    riesgo_eur: float
    motivo: str | None = None   # None = aceptada


def redondear_unidades(unidades: float, es_cripto: bool) -> float:
    """Acciones y ETFs: enteras hacia abajo. Cripto: decimales (6) hacia abajo."""
    if unidades <= 0 or not math.isfinite(unidades):
        return 0.0
    if es_cripto:
        return math.floor(unidades * 1e6) / 1e6
    return float(math.floor(unidades))


def tamano(
    capital_eur: float,
    entrada_eur: float,
    stop_eur: float,
    es_cripto: bool,
    p: dict,
    efectivo_eur: float | None = None,
    exposicion_cripto_eur: float = 0.0,
) -> Propuesta:
    """unidades = capital × riesgo / (entrada − stop), con los topes de tamaño máximo,
    exposición cripto y efectivo disponible; se descarta si queda por debajo del mínimo."""
    riesgo_ud = entrada_eur - stop_eur
    if riesgo_ud <= 0 or entrada_eur <= 0:
        return Propuesta(0, 0, 0, BAJO_MINIMO)
    importe = capital_eur * p["riesgo_por_operacion"] / riesgo_ud * entrada_eur
    importe = min(importe, capital_eur * p["tamano_maximo"])
    motivo_tope = BAJO_MINIMO
    if es_cripto:
        hueco = capital_eur * p["exposicion_maxima_cripto"] - exposicion_cripto_eur
        if hueco < importe:
            importe, motivo_tope = max(hueco, 0.0), LIMITE_CRIPTO
    if efectivo_eur is not None and efectivo_eur < importe:
        importe, motivo_tope = max(efectivo_eur, 0.0), SIN_LIQUIDEZ
    unidades = redondear_unidades(importe / entrada_eur, es_cripto)
    importe = unidades * entrada_eur
    if importe < p["tamano_minimo_eur"]:
        return Propuesta(0, 0, 0, motivo_tope)
    return Propuesta(unidades, importe, unidades * riesgo_ud)


def coste_operacion(importe_eur: float, es_cripto: bool, costes: dict) -> float:
    """Comisión en EUR de una compra o una venta (el deslizamiento va aparte, en el precio)."""
    c = costes["cripto" if es_cripto else "acciones_etfs"]
    return c.get("comision_eur", 0.0) + c.get("comision", 0.0) * importe_eur


def deslizamiento(es_cripto: bool, costes: dict) -> float:
    return costes["cripto" if es_cripto else "acciones_etfs"]["deslizamiento"]
