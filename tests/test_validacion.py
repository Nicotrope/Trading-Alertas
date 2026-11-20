from datetime import date

import numpy as np
import pandas as pd

from src.config import cargar_yaml
from src.datos.validacion import validar
from tests.conftest import velas_aleatorias

P = cargar_yaml("datos.yaml")["validacion"]


def base(n=400, diario=False):
    d = velas_aleatorias(n, diario=diario)
    return d, d.index[-1].date()


def tipos(r, severidad=None):
    return {i.tipo for i in r.incidencias if severidad is None or i.severidad == severidad}


def test_datos_limpios_son_aptos():
    d, fin = base()
    r = validar("X", d, fin, P)
    assert r.apto and not r.incidencias


def test_sin_datos():
    assert not validar("X", pd.DataFrame(), date(2026, 1, 1), P).apto


def test_precio_cero_reciente_excluye():
    d, fin = base()
    d.iloc[-3, d.columns.get_loc("close")] = 0.0
    r = validar("X", d, fin, P)
    assert not r.apto and "precio_cero" in tipos(r, "error")


def test_nan_reciente_excluye():
    d, fin = base()
    d.iloc[-2, d.columns.get_loc("open")] = np.nan
    assert "nan" in tipos(validar("X", d, fin, P), "error")


def test_salto_mayor_50_reciente_excluye():
    d, fin = base()
    d.iloc[-5:, :4] *= 1.8   # +80 % en un día y se mantiene
    r = validar("X", d, fin, P)
    assert not r.apto and "salto" in tipos(r, "error")


def test_salto_antiguo_solo_avisa():
    d, fin = base()
    d.iloc[:100, :4] *= 0.4  # caída aparente del 60 % hace más de un año (p. ej. split mal ajustado)
    r = validar("X", d, fin, P)
    assert r.apto and "salto" in tipos(r, "aviso")


def test_salto_de_49_no_es_incidencia():
    d, fin = base()
    d.iloc[-5:, :4] *= 1.49
    d.iloc[-5, d.columns.get_loc("open")] = d.iloc[-5]["close"]
    assert "salto" not in tipos(validar("X", d, fin, P))


def test_hueco_reciente_en_acciones():
    d, fin = base()
    d = d.drop(d.index[-12:-6])   # 6 días hábiles sin velas
    assert "hueco" in tipos(validar("X", d, fin, P), "error")


def test_festivo_no_es_hueco():
    d, fin = base()
    d = d.drop(d.index[-10:-8])   # 2 días sin velas (Semana Santa)
    assert validar("X", d, fin, P).apto


def test_cripto_un_dia_faltante_es_hueco():
    d, fin = base(diario=True)
    d = d.drop(d.index[-4])
    assert "hueco" in tipos(validar("BTC/EUR", d, fin, P, diario=True), "error")


def test_desfasado():
    d, fin = base()
    r = validar("X", d.iloc[:-10], fin, P)
    assert not r.apto and "desfasado" in tipos(r)


def test_falta_solo_la_ultima_vela_avisa():
    d, fin = base()
    r = validar("X", d.iloc[:-1], fin, P)
    assert r.apto and "sin_ultima_vela" in tipos(r, "aviso")


def test_vela_futura_es_error():
    d, fin = base()
    r = validar("X", d, d.index[-3].date(), P)
    assert "vela_futura" in tipos(r, "error")


def test_historia_corta():
    d, fin = base(n=100)
    assert "historia_corta" in tipos(validar("X", d, fin, P), "error")


def test_vela_incoherente():
    d, fin = base()
    d.iloc[-2, d.columns.get_loc("high")] = d.iloc[-2]["close"] * 0.9
    assert "vela_incoherente" in tipos(validar("X", d, fin, P), "error")
