from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from src.datos.calendario import ultima_vela_cerrada

AMS = ZoneInfo("Europe/Amsterdam")


def t(*a):
    return datetime(*a, tzinfo=AMS)


@pytest.mark.parametrize("ahora, corte, esperada", [
    (t(2026, 11, 20, 13, 56), "22:30", date(2026, 11, 19)),  # viernes antes del cierre de EE. UU.
    (t(2026, 11, 20, 22, 30), "22:30", date(2026, 11, 20)),  # justo en la hora de corte
    (t(2026, 11, 20, 18, 5), "18:00", date(2026, 11, 20)),   # Europa ya cerró
    (t(2026, 11, 21, 12, 0), "22:30", date(2026, 11, 20)),   # sábado → viernes
    (t(2026, 11, 23, 7, 0), "22:30", date(2026, 11, 20)),    # lunes 07:00 → viernes
    (t(2026, 7, 14, 7, 0), "18:00", date(2026, 7, 13)),      # horario de verano
])
def test_acciones(ahora, corte, esperada):
    assert ultima_vela_cerrada(ahora, corte) == esperada


@pytest.mark.parametrize("ahora, esperada", [
    (t(2026, 11, 21, 7, 0), date(2026, 11, 20)),   # email de las 07:00: vela UTC de ayer cerrada
    (t(2026, 11, 21, 1, 0), date(2026, 11, 19)),   # antes de 01:30 aún no se da por cerrada
    (t(2026, 11, 22, 7, 0), date(2026, 11, 21)),   # cripto cotiza en fin de semana
])
def test_cripto(ahora, esperada):
    assert ultima_vela_cerrada(ahora, "01:30", desfase_dias=1, solo_dias_habiles=False) == esperada


def test_exige_zona_horaria():
    with pytest.raises(ValueError):
        ultima_vela_cerrada(datetime(2026, 11, 20, 12), "22:30")
