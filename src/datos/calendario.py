"""Qué vela diaria está cerrada en un momento dado (evita usar velas a medio formar)."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo


def _hora(texto: str) -> time:
    h, m = texto.split(":")
    return time(int(h), int(m))


def ultima_vela_cerrada(
    ahora: datetime,
    hora_corte: str,
    zona: str = "Europe/Amsterdam",
    desfase_dias: int = 0,
    solo_dias_habiles: bool = True,
) -> date:
    """Fecha de la última vela diaria completa en el instante `ahora`.

    - Acciones/ETFs (desfase 0): a partir de `hora_corte` (hora de Ámsterdam) la vela
      de hoy está cerrada; antes, la última cerrada es la de ayer. Se salta el fin de semana.
    - Cripto (desfase 1): a las 01:30 del día D se acaba de cerrar la vela del día D-1.
    """
    if ahora.tzinfo is None:
        raise ValueError("`ahora` debe llevar zona horaria")
    local = ahora.astimezone(ZoneInfo(zona))
    d = local.date() - timedelta(days=desfase_dias)
    if local.time() < _hora(hora_corte):
        d -= timedelta(days=1)
    if solo_dias_habiles:
        while d.weekday() >= 5:
            d -= timedelta(days=1)
    return d
