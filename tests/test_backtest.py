"""Motor de backtest: un caso calculado a mano y la comprobación de no mirar al futuro."""
import math

import numpy as np
import pandas as pd
import pytest
import yaml

from backtest.motor import calcular_senales, cargar_mercado, limpiar, simular
from src import indicadores as ind
from src.config import cargar_universo
from tests.conftest import velas_aleatorias

ESTR = {
    "indicadores": {"sma_tendencia": 5, "atr": 3, "momentum_sesiones": 3},
    "ruptura": {"maximo_cierres": 3, "salida_minimo": 2, "stop_atr": 2.0, "stop_dinamico_atr": 3.0},
    "retroceso": {"rsi_periodo": 2, "rsi_entrada": 10, "rsi_salida": 70, "sma_salida": 5, "stop_atr": 2.0,
                  "sesiones_maximas": 10},
    "regimen": {"sma": 5},
}
RIESGO = {
    "capital_eur": 10_000, "riesgo_por_operacion": 0.01, "posiciones_maximas": 8, "tamano_maximo": 0.20,
    "exposicion_maxima_cripto": 0.20, "posiciones_maximas_por_sector": 2, "tamano_minimo_eur": 500,
    "freno_caida": 0.10, "freno_pausa_sesiones": 20,
    "costes": {"acciones_etfs": {"comision_eur": 1.0, "comision": 0.0, "deslizamiento": 0.001},
               "cripto": {"comision_eur": 1.0, "comision": 0.0, "deslizamiento": 0.005}},
}


def universo(tmp_path, simbolos, sector=None):
    cfg = {"grupos": {"europa": {
        "nombre": "Europa", "proveedor": "yahoo", "moneda": "EUR", "referencia": "REF", "hora_corte": "18:00",
        "activos": [{"simbolo": s, "nombre": s, "sector": sector or f"sector_{s}"} for s in simbolos]}},
        "auxiliares": [{"simbolo": "REF", "proveedor": "yahoo", "grupo_calendario": "europa", "uso": "referencia"}]}
    (tmp_path / "universo.yaml").write_text(yaml.safe_dump(cfg))
    return cargar_universo(tmp_path)


def subida(n=40):
    f = pd.date_range("2024-01-01", periods=n, freq="B")
    c = pd.Series(np.linspace(100, 140, n), index=f)
    return pd.DataFrame({"open": c, "high": c + 1, "low": c - 1, "close": c})


def test_caso_a_mano(tmp_path):
    u = universo(tmp_path, ["X"])
    f = pd.date_range("2024-01-01", periods=12, freq="B")
    close = np.array([10, 10.5, 11, 11.5, 12, 12.5, 13, 8, 8, 8, 8, 8])
    open_ = np.r_[10, close[:-1]]
    open_[7] = 8                                       # hueco a la baja el día 7
    x = pd.DataFrame({"open": open_, "high": np.maximum(open_, close) + 0.25,
                      "low": np.minimum(open_, close) - 0.25, "close": close}, index=f, dtype=float)
    velas = {"X": x, "REF": subida(12).set_index(f)}
    m = cargar_mercado(u, velas=velas, sma_regimen=5)
    sen = calcular_senales(m, ESTR)
    res = simular(m, sen, ESTR, RIESGO, usar=("A",))

    # Señal A el día 4 (cierre 12 > SMA5 = 11 y >= máx(10,5; 11; 11,5)); compra en la apertura del día 5
    atr4 = ind.atr(x["high"], x["low"], x["close"], 3).iloc[4]
    unidades = math.floor(min(100 / (2 * atr4) * 12, 2000) / 12)
    entrada = 12 * 1.001                                # apertura del día 5 = 12, +0,1 % de deslizamiento
    stop = entrada - 2 * atr4
    assert len(res.operaciones) == 1
    op = res.operaciones.iloc[0]
    assert op["fecha_entrada"] == f[5] and op["unidades"] == unidades
    assert op["precio_entrada"] == pytest.approx(entrada) and op["stop_inicial"] == pytest.approx(stop)
    # Día 7: abre en 8, por debajo del stop → se vende a la apertura (no al stop), −0,1 %
    assert op["fecha_salida"] == f[7] and op["motivo_salida"] == "stop"
    assert op["precio_salida"] == pytest.approx(8 * 0.999)
    pnl = unidades * (8 * 0.999 - entrada) - 2          # 1 € al comprar y 1 € al vender
    assert op["resultado_eur"] == pytest.approx(pnl)
    assert res.capital.iloc[-1] == pytest.approx(10_000 + pnl)


def test_regimen_bajista_bloquea_compras(tmp_path):
    u = universo(tmp_path, ["X"])
    x = subida(40)
    ref = x.copy()
    ref[["open", "high", "low", "close"]] = ref[["open", "high", "low", "close"]].to_numpy()[::-1]   # referencia bajando
    m = cargar_mercado(u, velas={"X": x, "REF": ref}, sma_regimen=5)
    res = simular(m, calcular_senales(m, ESTR), ESTR, RIESGO)
    assert res.operaciones.empty


def test_limite_de_sector_y_huecos(tmp_path):
    simbolos = [f"S{i}" for i in range(5)]
    u = universo(tmp_path, simbolos, sector="mismo")
    velas = {s: subida(40) * (1 + i / 10) for i, s in enumerate(simbolos)}
    velas["REF"] = subida(40)
    m = cargar_mercado(u, velas=velas, sma_regimen=5)
    res = simular(m, calcular_senales(m, ESTR), ESTR, RIESGO, usar=("A",))
    assert res.operaciones["activo"].nunique() == 2      # máx. 2 posiciones por sector
    assert res.descartes.get("límite sector", 0) > 0


@pytest.mark.parametrize("corte", [260, 330, 420])
def test_no_mira_al_futuro(tmp_path, corte):
    """Cortar los datos en T no cambia el capital ni las operaciones cerradas antes de T."""
    simbolos = [f"Z{i}" for i in range(6)]
    u = universo(tmp_path, simbolos)
    velas = {s: limpiar(velas_aleatorias(500, semilla=10 + i)) for i, s in enumerate(simbolos)}
    velas["REF"] = limpiar(velas_aleatorias(500, semilla=99))
    estr = {**ESTR, "indicadores": {"sma_tendencia": 50, "atr": 14, "momentum_sesiones": 20}, "regimen": {"sma": 50}}
    completo = simular(*(lambda m: (m, calcular_senales(m, estr)))(cargar_mercado(u, velas=velas, sma_regimen=50)),
                       estr, RIESGO)
    T = velas["REF"].index[corte]
    cortadas = {s: v[v.index <= T] for s, v in velas.items()}
    m2 = cargar_mercado(u, velas=cortadas, sma_regimen=50)
    parcial = simular(m2, calcular_senales(m2, estr), estr, RIESGO)
    assert len(completo.operaciones) > 5
    pd.testing.assert_series_equal(parcial.capital, completo.capital.loc[:T])
    def cerradas(r):
        o = r.operaciones
        return o[(o["fecha_salida"] < T) & (o["motivo_salida"] != "abierta al final")].reset_index(drop=True)
    pd.testing.assert_frame_equal(cerradas(parcial), cerradas(completo))
