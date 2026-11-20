"""Ningún indicador usa datos posteriores al día evaluado.

Dos comprobaciones para cada indicador y varios días t:
1. calcular con la serie cortada en t da el mismo valor en t que con la serie completa;
2. cambiar todos los datos posteriores a t no altera ningún valor hasta t.
"""
import numpy as np
import pandas as pd
import pytest

from src import indicadores as ind
from tests.conftest import velas_aleatorias

INDICADORES = {
    "sma200": lambda d: ind.sma(d["close"], 200),
    "sma5": lambda d: ind.sma(d["close"], 5),
    "atr14": lambda d: ind.atr(d["high"], d["low"], d["close"], 14),
    "rsi2": lambda d: ind.rsi(d["close"], 2),
    "rsi14": lambda d: ind.rsi(d["close"], 14),
    "max20": lambda d: ind.maximo_previo(d["close"], 20),
    "min10": lambda d: ind.minimo_previo(d["close"], 10),
    "mom126": lambda d: ind.rentabilidad(d["close"], 126),
}
DIAS = [0, 1, 13, 14, 150, 199, 250, 398]


@pytest.mark.parametrize("nombre", INDICADORES)
def test_cortar_en_t_no_cambia_el_valor(nombre):
    d = velas_aleatorias(400, semilla=7)
    f = INDICADORES[nombre]
    completo = f(d)
    for t in DIAS:
        cortado = f(d.iloc[: t + 1])
        pd.testing.assert_series_equal(cortado, completo.iloc[: t + 1], check_names=False)


@pytest.mark.parametrize("nombre", INDICADORES)
def test_cambiar_el_futuro_no_cambia_el_pasado(nombre):
    d = velas_aleatorias(400, semilla=3)
    f = INDICADORES[nombre]
    original = f(d)
    rng = np.random.default_rng(0)
    for t in DIAS[:-1]:
        alterado = d.copy()
        factor = rng.uniform(0.3, 3.0, size=(len(d) - t - 1, 1))
        alterado.iloc[t + 1:, :4] = alterado.iloc[t + 1:, :4].to_numpy() * factor
        pd.testing.assert_series_equal(f(alterado).iloc[: t + 1], original.iloc[: t + 1], check_names=False)


def test_tabla_completa_sin_futuro():
    from src.config import cargar_yaml

    est = cargar_yaml("estrategias.yaml")
    d = velas_aleatorias(400, semilla=11)
    completo = ind.tabla_indicadores(d, est)
    for t in (100, 250, 399):
        pd.testing.assert_frame_equal(ind.tabla_indicadores(d.iloc[: t + 1], est), completo.iloc[: t + 1])
