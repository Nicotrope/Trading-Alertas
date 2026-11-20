import numpy as np
import pandas as pd
import pytest


def velas_aleatorias(n: int = 400, semilla: int = 1, diario: bool = False, inicio="2020-01-01") -> pd.DataFrame:
    rng = np.random.default_rng(semilla)
    fechas = pd.date_range(inicio, periods=n, freq="D" if diario else "B", name="fecha")
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.02, n)))
    open_ = close * (1 + rng.normal(0, 0.005, n))
    high = np.maximum(open_, close) * (1 + rng.uniform(0, 0.01, n))
    low = np.minimum(open_, close) * (1 - rng.uniform(0, 0.01, n))
    vol = rng.integers(1_000, 10_000, n).astype(float)
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": vol}, index=fechas)


@pytest.fixture
def velas():
    return velas_aleatorias()
