"""Tamaño de posición y límites (SPEC §4)."""
import pytest

from src import riesgo
from src.config import cargar_yaml

P = {"riesgo_por_operacion": 0.01, "tamano_maximo": 0.20, "exposicion_maxima_cripto": 0.20, "tamano_minimo_eur": 500}


def test_formula_basica():
    # 10.000 × 1 % = 100 € de riesgo; entrada 20, stop 18 → 2 €/ud → 50 uds = 1.000 € (< 20 %)
    p = riesgo.tamano(10_000, 20, 18, False, P)
    assert p.unidades == 50 and p.importe_eur == 1000 and p.riesgo_eur == 100 and p.motivo is None


def test_tope_20_por_ciento_y_unidades_enteras():
    # riesgo pequeño por unidad → pediría 100/0,5 = 200 uds × 100 = 20.000 €; tope 2.000 € → 20 uds
    p = riesgo.tamano(10_000, 100, 99.5, False, P)
    assert p.unidades == 20 and p.importe_eur == 2000
    p = riesgo.tamano(10_000, 333, 300, False, P)   # 100/33 = 3,03 uds → 3 enteras
    assert p.unidades == 3


def test_cripto_admite_decimales_y_limite_exposicion():
    p = riesgo.tamano(10_000, 40_000, 36_000, True, P)   # 100/4000 = 0,025 BTC = 1.000 €
    assert p.unidades == pytest.approx(0.025) and p.motivo is None
    p = riesgo.tamano(10_000, 40_000, 36_000, True, P, exposicion_cripto_eur=1_700)   # quedan 300 € < 500
    assert p.motivo == riesgo.LIMITE_CRIPTO and p.unidades == 0


def test_minimo_y_liquidez():
    assert riesgo.tamano(10_000, 20, 18, False, P, efectivo_eur=400).motivo == riesgo.SIN_LIQUIDEZ
    p = riesgo.tamano(10_000, 50, 48, False, P, efectivo_eur=1_000)   # 1.000 € / 50 = 20 uds
    assert p.unidades == 20 and p.motivo is None
    # riesgo enorme por unidad → posición diminuta → descartada por mínimo
    assert riesgo.tamano(10_000, 100, 1, False, P).motivo == riesgo.BAJO_MINIMO


def test_costes_trade_republic_en_config():
    c = cargar_yaml("riesgo.yaml")["costes"]
    assert riesgo.coste_operacion(2_000, False, c) == 1.0
    assert riesgo.coste_operacion(2_000, True, c) == 1.0
    assert riesgo.deslizamiento(True, c) > riesgo.deslizamiento(False, c)
