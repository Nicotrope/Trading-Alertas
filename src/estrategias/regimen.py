"""Filtro de régimen (SPEC §3): no se abren compras en un grupo si su índice de
referencia cierra por debajo de su SMA de 200 días."""
from __future__ import annotations

import pandas as pd

from src import indicadores as ind


def alcista(referencia: pd.DataFrame, n: int = 200) -> pd.Series:
    """True el día t si cierre_t > SMA(n)_t. Sin historia suficiente → False."""
    c = referencia["close"]
    return (c > ind.sma(c, n)).fillna(False).astype(bool)
