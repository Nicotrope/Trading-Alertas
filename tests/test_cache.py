from datetime import date

import pandas as pd
import pytest

from src.datos.cache import CacheParquet, actualizar
from src.datos.proveedor import DataProvider, recortar
from tests.conftest import velas_aleatorias


class Falso(DataProvider):
    """Proveedor en memoria que registra qué rangos se le piden."""

    def __init__(self, datos: pd.DataFrame, nombre="falso"):
        self.datos = datos
        self.nombre = nombre
        self.peticiones: list[tuple[date, date]] = []

    def descargar(self, simbolo, desde, hasta):
        self.peticiones.append((desde, hasta))
        return recortar(self.datos, desde, hasta)


@pytest.fixture
def cache(tmp_path):
    return CacheParquet(tmp_path)


def test_primera_descarga_y_luego_incremental(cache):
    todo = velas_aleatorias(400)
    p = Falso(todo)
    corte = todo.index[349].date()
    r = actualizar(cache, p, "AAA", corte, date(2000, 1, 1))
    assert r.accion == "completa" and len(r.datos) == 350

    fin = todo.index[-1].date()
    r = actualizar(cache, p, "AAA", fin, date(2000, 1, 1), dias_solape=10)
    assert r.accion == "incremental" and r.nuevas == 50 and len(r.datos) == 400
    assert p.peticiones[-1][0] > date(2000, 1, 1)           # solo pidió lo reciente
    pd.testing.assert_frame_equal(cache.leer("AAA")[todo.columns], todo, check_freq=False)


def test_nunca_guarda_velas_posteriores_a_hasta(cache):
    todo = velas_aleatorias(400)
    hasta = todo.index[300].date()
    r = actualizar(cache, Falso(todo), "AAA", hasta, date(2000, 1, 1))
    assert r.datos.index.max().date() == hasta
    assert cache.leer("AAA").index.max().date() == hasta


def test_cambio_de_ajuste_redescarga_todo(cache):
    todo = velas_aleatorias(400)
    actualizar(cache, Falso(todo), "AAA", todo.index[349].date(), date(2000, 1, 1))
    ajustado = todo.copy()
    ajustado.iloc[:, :4] *= 0.98                             # dividendo: toda la historia baja un 2 %
    p = Falso(ajustado)
    r = actualizar(cache, p, "AAA", todo.index[-1].date(), date(2000, 1, 1))
    assert r.accion == "redescarga_ajuste"
    pd.testing.assert_frame_equal(cache.leer("AAA")[todo.columns], ajustado, check_freq=False)


def test_cripto_completa_historia_con_respaldo(cache):
    todo = velas_aleatorias(2000, diario=True, inicio="2018-01-01")
    kraken = Falso(todo.iloc[-720:], nombre="kraken")        # el exchange solo tiene 720 velas
    yahoo = Falso(todo * 1.001, nombre="yahoo")
    r = actualizar(cache, kraken, "BTC/EUR", todo.index[-1].date(), date(2018, 1, 1),
                   respaldo=yahoo, simbolo_respaldo="BTC-EUR")
    assert len(r.datos) == 2000 and not r.datos.index.has_duplicates
    assert (r.datos["fuente"].iloc[-720:] == "kraken").all()
    assert (r.datos["fuente"].iloc[:-720] == "yahoo:BTC-EUR").all()
