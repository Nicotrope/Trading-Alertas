"""Métricas e informe HTML del backtest (SPEC §5)."""
from __future__ import annotations

import html
import math

import numpy as np
import pandas as pd


def _anios(curva: pd.Series) -> float:
    return max((curva.index[-1] - curva.index[0]).days / 365.25, 1e-9)


def metricas_curva(curva: pd.Series) -> dict:
    curva = curva.dropna()
    if len(curva) < 2:
        return {"cagr": np.nan, "max_caida": np.nan, "sharpe": np.nan, "final": np.nan}
    anios = _anios(curva)
    cagr = (curva.iloc[-1] / curva.iloc[0]) ** (1 / anios) - 1
    caida = (curva / curva.cummax() - 1).min()
    r = curva.pct_change().dropna()
    obs_anio = len(r) / anios
    sharpe = r.mean() / r.std() * math.sqrt(obs_anio) if r.std() > 0 else np.nan
    return {"cagr": cagr, "max_caida": caida, "sharpe": sharpe, "final": curva.iloc[-1]}


def metricas_operaciones(ops: pd.DataFrame) -> dict:
    if ops is None or ops.empty:
        return {"operaciones": 0, "aciertos": np.nan, "ganancia_media": np.nan, "perdida_media": np.nan,
                "ratio_gan_perd": np.nan, "duracion_media_dias": np.nan, "resultado_eur": 0.0, "costes_eur": 0.0}
    g = ops[ops["resultado_eur"] > 0]
    p = ops[ops["resultado_eur"] <= 0]
    gm = g["rentabilidad"].mean() if len(g) else np.nan
    pm = p["rentabilidad"].mean() if len(p) else np.nan
    return {
        "operaciones": len(ops),
        "aciertos": len(g) / len(ops),
        "ganancia_media": gm,
        "perdida_media": pm,
        "ratio_gan_perd": abs(gm / pm) if pm and not math.isnan(pm) and pm != 0 else np.nan,
        "duracion_media_dias": ops["dias"].mean(),
        "resultado_eur": ops["resultado_eur"].sum(),
        "costes_eur": ops["costes_eur"].sum(),
    }


def comprar_y_mantener(precio_eur: pd.Series, curva: pd.Series, capital: float) -> pd.Series:
    """Capital de invertir todo en la referencia el primer día del periodo y no tocarlo."""
    p = precio_eur.reindex(curva.index).ffill().bfill()
    return capital * p / p.iloc[0]


def criterio(fuera: dict, ref: dict, max_caida: float = 0.20, tolerancia_sharpe: float = 0.25) -> tuple[bool, str]:
    """SPEC §5: fuera de muestra, caída máxima ≤ 20 % y Sharpe no claramente peor que
    comprar y mantener (se interpreta como Sharpe ≥ Sharpe de la referencia − 0,25)."""
    ok_caida = -fuera["max_caida"] <= max_caida
    ok_sharpe = fuera["sharpe"] >= ref["sharpe"] - tolerancia_sharpe
    texto = (f"caída {-fuera['max_caida']:.1%} ({'≤' if ok_caida else '>'} {max_caida:.0%}); "
             f"Sharpe {fuera['sharpe']:.2f} vs referencia {ref['sharpe']:.2f} "
             f"({'OK' if ok_sharpe else 'peor'} con margen {tolerancia_sharpe})")
    return ok_caida and ok_sharpe, texto


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------

def _fmt(v, tipo: str) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "–"
    if tipo == "pct":
        return f"{v:.1%}".replace(".", ",")
    if tipo == "eur":
        return f"{v:,.0f} €".replace(",", ".")
    if tipo == "num2":
        return f"{v:.2f}".replace(".", ",")
    if tipo == "int":
        return f"{int(v)}"
    if tipo == "num1":
        return f"{v:.1f}".replace(".", ",")
    return html.escape(str(v))


COLUMNAS = [
    ("cagr", "Rent. anual", "pct"), ("max_caida", "Caída máx.", "pct"), ("sharpe", "Sharpe", "num2"),
    ("final", "Capital final", "eur"), ("ref_cagr", "Ref. rent. anual", "pct"), ("ref_max_caida", "Ref. caída", "pct"),
    ("ref_sharpe", "Ref. Sharpe", "num2"), ("operaciones", "Operaciones", "int"), ("aciertos", "Aciertos", "pct"),
    ("ganancia_media", "Ganancia media", "pct"), ("perdida_media", "Pérdida media", "pct"),
    ("duracion_media_dias", "Duración (días)", "num1"), ("costes_eur", "Costes", "eur"),
]


def tabla_html(filas: list[dict], primera: str, columnas=COLUMNAS) -> str:
    cab = "".join(f"<th>{html.escape(t)}</th>" for _, t, _ in columnas)
    cuerpo = []
    for f in filas:
        celdas = "".join(f"<td>{_fmt(f.get(k), tipo)}</td>" for k, _, tipo in columnas)
        cuerpo.append(f"<tr><th>{html.escape(str(f[primera]))}</th>{celdas}</tr>")
    return f"<table><thead><tr><th></th>{cab}</tr></thead><tbody>{''.join(cuerpo)}</tbody></table>"


ESTILO = """
:root{--fondo:#fff;--texto:#1b1f24;--suave:#5b6470;--borde:#dde1e6;--ok:#1a7f37;--mal:#c62828;--cab:#f4f6f8}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){--fondo:#14171a;--texto:#e6e9ec;--suave:#9aa4ae;--borde:#2c3238;--ok:#4cc26b;--mal:#ef6a6a;--cab:#1c2024}}
body{background:var(--fondo);color:var(--texto);font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif;margin:0;padding:24px 16px;max-width:1200px;margin:auto}
h1{font-size:1.6em;margin:.2em 0}h2{margin-top:2em;border-bottom:1px solid var(--borde);padding-bottom:.2em}
p.nota,li{color:var(--suave)} .tabla{overflow-x:auto} table{border-collapse:collapse;font-size:13px;white-space:nowrap}
td,th{border:1px solid var(--borde);padding:4px 8px;text-align:right} thead th{background:var(--cab)} tbody th{text-align:left}
.ok{color:var(--ok);font-weight:600}.mal{color:var(--mal);font-weight:600}
"""
