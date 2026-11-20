"""Reglas de señales A y B (SPEC §3) sobre series construidas a mano."""
import numpy as np
import pandas as pd

from src.estrategias import regimen, retroceso, ruptura

P_IND = {"sma_tendencia": 5, "atr": 3}
P_A = {"maximo_cierres": 3, "salida_minimo": 2, "stop_atr": 2.0, "stop_dinamico_atr": 3.0}
P_B = {"rsi_periodo": 2, "rsi_entrada": 10, "rsi_salida": 70, "sma_salida": 3, "stop_atr": 2.0, "sesiones_maximas": 10}


def velas(cierres):
    c = pd.Series(cierres, dtype=float, index=pd.date_range("2024-01-01", periods=len(cierres), freq="B"))
    return pd.DataFrame({"open": c, "high": c + 1, "low": c - 1, "close": c})


def test_ruptura_entrada_y_salida():
    s = ruptura.senales(velas([10, 11, 12, 13, 14, 15, 14, 16, 13, 12]), P_A, P_IND)
    # t=5: cierre 15 > SMA5 (13) y >= máx(12,13,14) → entrada
    assert bool(s["entrada"].iloc[5])
    # t=6: 14 < máx previo 15 → no
    assert not s["entrada"].iloc[6]
    # t=7: 16 >= máx(14,15,14)=15 y > SMA5 → entrada
    assert bool(s["entrada"].iloc[7])
    # t=8: 13 < mín(14,16)=14 → salida
    assert bool(s["salida"].iloc[8]) and not s["salida"].iloc[7]
    # sin historia suficiente para la SMA → nunca entrada
    assert not s["entrada"].iloc[:4].any()


def test_ruptura_stops():
    assert ruptura.stop_inicial(100, 5, P_A) == 90
    assert ruptura.stop_dinamico(90, 120, 5, P_A) == 105        # 120 − 3×5
    assert ruptura.stop_dinamico(105, 108, 5, P_A) == 105       # solo sube
    assert ruptura.sesiones_maximas(P_A) is None


def test_retroceso_entrada_y_salida():
    # subida de 2 en 2 y dos caídas: RSI(2) = 100 → 28,6 → 25,0; SMA10 = 22,3 / 23,35
    cierres = list(range(10, 32, 2)) + [25, 24.5, 30]
    p = {**P_B, "rsi_entrada": 30}
    s = retroceso.senales(velas(cierres), p, {**P_IND, "sma_tendencia": 10})
    assert not s["entrada"].iloc[:11].any()
    assert bool(s["entrada"].iloc[11]) and bool(s["entrada"].iloc[12])   # RSI2 < 30 y cierre > SMA10
    # con el umbral estándar (10) no hay entrada
    assert not retroceso.senales(velas(cierres), P_B, {**P_IND, "sma_tendencia": 10})["entrada"].any()
    assert bool(s["salida"].iloc[13])      # 30 > SMA3 (26,5) → salida (también RSI2 = 80 > 70)
    assert not s["salida"].iloc[12]        # 24,5 < SMA3 (26,5) y RSI2 = 25
    assert retroceso.stop_dinamico(90, 200, 1, P_B) == 90
    assert retroceso.sesiones_maximas(P_B) == 10


def test_regimen():
    ref = velas([10, 10, 10, 10, 10, 11, 9])
    r = regimen.alcista(ref, 5)
    assert list(r) == [False, False, False, False, False, True, False]
