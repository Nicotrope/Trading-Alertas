"""Flujo completo de actualización con proveedores falsos (sin red)."""
from datetime import datetime, timezone

import pandas as pd

from src.config import cargar_universo
from src.datos.actualizar import ejecutar, tareas
from src.datos.proveedor import DataProvider, ErrorDatos, recortar
from tests.conftest import velas_aleatorias


class Falso(DataProvider):
    def __init__(self, nombre, diario=False, rotos=()):
        self.nombre, self.diario, self.rotos = nombre, diario, set(rotos)

    def descargar(self, simbolo, desde, hasta):
        if simbolo in self.rotos:
            raise ErrorDatos(f"{simbolo}: no encontrado")
        semilla = sum(map(ord, simbolo))
        d = recortar(velas_aleatorias(6000, semilla=semilla, diario=self.diario, inicio="2010-01-01"), None, hasta)
        if self.nombre == "kraken":
            d = d.iloc[-720:]   # como la API pública de Kraken
        return recortar(d, desde, None)


def test_universo_sin_duplicados_y_tamano():
    u = cargar_universo()
    assert 150 <= len(u.activos()) <= 200
    assert {"eeuu", "europa", "etfs", "cripto"} == set(u.grupos)
    assert all(a.simbolo_historia for a in u.grupos["cripto"].activos)


def test_referencias_incluidas():
    simbolos = {t.simbolo for t in tareas(cargar_universo())}
    assert {"SPY", "^STOXX50E", "EURUSD=X", "BTC/EUR"} <= simbolos


def test_ejecutar_con_proveedores_falsos(tmp_path):
    ahora = datetime(2023, 9, 13, 6, 0, tzinfo=timezone.utc)   # miércoles 08:00 en Ámsterdam
    prov = {"yahoo": Falso("yahoo", rotos={"ASML.AS"}), "kraken": Falso("kraken", diario=True)}
    informe = ejecutar(ahora=ahora, proveedores=prov, carpeta_cache=tmp_path)
    fila = informe.set_index("simbolo")
    assert not fila.at["ASML.AS", "apto"] and fila.at["ASML.AS", "accion"] == "fallo_descarga"
    assert str(fila.at["AAPL", "hasta"]) == "2023-09-12"         # vela del martes; la del miércoles aún no ha cerrado
    assert str(fila.at["BTC/EUR", "hasta"]) == "2023-09-12"
    # El respaldo falso de Yahoo no tiene fines de semana: huecos antiguos → aviso, no exclusión
    assert fila.at["BTC/EUR", "apto"] and fila.at["BTC/EUR", "avisos"] > 0
    assert (tmp_path / "informe_validacion.csv").exists()
    # segunda pasada: incremental, sin redescargas
    informe2 = ejecutar(ahora=ahora, proveedores=prov, carpeta_cache=tmp_path)
    assert set(informe2.loc[informe2.apto, "accion"]) <= {"sin_cambios", "incremental"}
