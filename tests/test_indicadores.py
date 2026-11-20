"""Indicadores contra valores calculados a mano (ver los comentarios de cada test)."""
import numpy as np
import pandas as pd
import pytest

from src import indicadores as ind

S = lambda xs: pd.Series(xs, dtype=float)  # noqa: E731


def test_sma_a_mano():
    # (1+2+3)/3=2, (2+3+4)/3=3, (3+4+5)/3=4
    r = ind.sma(S([1, 2, 3, 4, 5]), 3)
    assert r.iloc[:2].isna().all()
    assert r.iloc[2:].tolist() == [2.0, 3.0, 4.0]


# Datos para ATR(3):
#   H = 10 12 11 15 14
#   L =  8 10  9 11 12
#   C =  9 11 10 14 13
# TR: t0 = H-L = 2
#     t1 = max(2, |12-9|=3, |10-9|=1)  = 3
#     t2 = max(2, |11-11|=0, |9-11|=2) = 2
#     t3 = max(4, |15-10|=5, |11-10|=1) = 5
#     t4 = max(2, |14-14|=0, |12-14|=2) = 2
# ATR: t2 = (2+3+2)/3 = 7/3
#      t3 = (7/3*2 + 5)/3 = 29/9
#      t4 = (29/9*2 + 2)/3 = 76/27
H, L, C = S([10, 12, 11, 15, 14]), S([8, 10, 9, 11, 12]), S([9, 11, 10, 14, 13])


def test_rango_verdadero_a_mano():
    assert ind.rango_verdadero(H, L, C).tolist() == [2, 3, 2, 5, 2]


def test_atr_wilder_a_mano():
    r = ind.atr(H, L, C, 3)
    assert r.iloc[:2].isna().all()
    assert r.iloc[2:].to_numpy() == pytest.approx([7 / 3, 29 / 9, 76 / 27])


# RSI(2) con C = 10, 11, 10.5, 12, 11, 11.5
# variaciones:   +1, -0.5, +1.5, -1, +0.5
# t2: subida media (1+0)/2 = 0.5, bajada media (0+0.5)/2 = 0.25 → RS 2   → 100-100/3   = 66.667
# t3: s = (0.5+1.5)/2 = 1,     b = (0.25+0)/2 = 0.125          → RS 8   → 100-100/9   = 88.889
# t4: s = (1+0)/2 = 0.5,       b = (0.125+1)/2 = 0.5625        → RS 8/9 → 100-100/(17/9) = 47.059
# t5: s = (0.5+0.5)/2 = 0.5,   b = 0.5625/2 = 0.28125          → RS 16/9→ 100-100/(25/9) = 64
def test_rsi_wilder_a_mano():
    r = ind.rsi(S([10, 11, 10.5, 12, 11, 11.5]), 2)
    assert r.iloc[:2].isna().all()
    assert r.iloc[2:].to_numpy() == pytest.approx([200 / 3, 800 / 9, 100 - 900 / 17, 64.0])


def test_rsi_extremos():
    assert ind.rsi(S([1, 2, 3, 4, 5]), 2).iloc[-1] == 100.0   # solo subidas
    assert ind.rsi(S([5, 4, 3, 2, 1]), 2).iloc[-1] == 0.0     # solo bajadas
    assert ind.rsi(S([3, 3, 3, 3, 3]), 2).iloc[-1] == 50.0    # sin movimiento


def test_rsi_entre_0_y_100(velas):
    r = ind.rsi(velas["close"], 2).dropna()
    assert ((r >= 0) & (r <= 100)).all()


# C = 5 3 4 6 2 7, ventana 3 de valores ANTERIORES:
# t3: max(5,3,4)=5 min=3 · t4: max(3,4,6)=6 min=3 · t5: max(4,6,2)=6 min=2
def test_maximo_minimo_previo_a_mano():
    c = S([5, 3, 4, 6, 2, 7])
    mx, mn = ind.maximo_previo(c, 3), ind.minimo_previo(c, 3)
    assert mx.iloc[:3].isna().all() and mn.iloc[:3].isna().all()
    assert mx.iloc[3:].tolist() == [5, 6, 6]
    assert mn.iloc[3:].tolist() == [3, 3, 2]


def test_maximo_previo_excluye_el_dia_actual():
    # El cierre de t (100) no cuenta en el máximo de t: así "cierre >= máximo previo" detecta la ruptura.
    c = S([1, 2, 3, 100])
    assert ind.maximo_previo(c, 3).iloc[-1] == 3


def test_rentabilidad_a_mano():
    # n=2: 4/5-1=-0.2, 6/3-1=1, 2/4-1=-0.5, 7/6-1
    r = ind.rentabilidad(S([5, 3, 4, 6, 2, 7]), 2)
    assert r.iloc[2:].to_numpy() == pytest.approx([-0.2, 1.0, -0.5, 7 / 6 - 1])


def test_historia_insuficiente_da_nan():
    c = S([1, 2, 3])
    assert ind.sma(c, 5).isna().all()
    assert ind.rsi(c, 5).isna().all()
    assert ind.atr(c, c, c, 5).isna().all()


def test_rechaza_nan():
    with pytest.raises(ValueError):
        ind.sma(S([1, np.nan, 3]), 2)


def test_tabla_indicadores_usa_parametros_del_yaml(velas):
    from src.config import cargar_yaml

    t = ind.tabla_indicadores(velas, cargar_yaml("estrategias.yaml"))
    assert {"sma200", "sma5", "atr14", "rsi2", "max20", "min10", "mom126"} <= set(t.columns)
    assert t["sma200"].iloc[199:].notna().all() and t["sma200"].iloc[:199].isna().all()
