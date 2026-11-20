"""Ejecuta el backtest completo y escribe el informe HTML. Uso:

    python -m backtest.ejecutar            # todo (≈ unos minutos)
    python -m backtest.ejecutar --rapido   # sin la prueba de robustez

Necesita la caché de datos (python -m src.datos.actualizar).
Resultados en backtest/resultados/: informe.html y operaciones_*.csv.
"""
from __future__ import annotations

import argparse
import html
import json
import time

import pandas as pd

from backtest import informe as inf
from backtest.motor import Mercado, calcular_senales, cargar_mercado, simular, variar
from src.config import RAIZ, cargar_universo, cargar_yaml

ESTRATEGIAS_RUN = {"A+B": ("A", "B"), "A": ("A",), "B": ("B",)}
NOMBRES = {"A+B": "A + B juntas", "A": "A. Ruptura", "B": "B. Retroceso"}
NOMBRE_GRUPO = {"eeuu": "Acciones EE. UU.", "europa": "Acciones Europa", "etfs": "ETFs", "cripto": "Cripto"}


def _periodos(cfg: dict) -> dict[str, tuple]:
    return {
        "Dentro de muestra": (cfg["dentro_de_muestra"]["desde"], cfg["dentro_de_muestra"]["hasta"]),
        "Fuera de muestra": (cfg["fuera_de_muestra"]["desde"], cfg["fuera_de_muestra"]["hasta"]),
    }


def _fila(res, ref_precio: pd.Series) -> dict:
    curva = res.capital
    bh = inf.comprar_y_mantener(ref_precio, curva, res.capital_inicial)
    f = {**inf.metricas_curva(curva), **inf.metricas_operaciones(res.operaciones)}
    for k, v in inf.metricas_curva(bh).items():
        f[f"ref_{k}"] = v
    return f


def _grafico(curvas: dict[str, pd.Series], titulo: str, div: str) -> str:
    datos = []
    colores = ["#2a6fdb", "#1a9e57", "#8e5bd0", "#9aa4ae"]
    for n, (nombre, c) in enumerate(curvas.items()):
        color = colores[n % len(colores)]
        c = c.resample("W").last().dropna()
        datos.append({"x": [d.strftime("%Y-%m-%d") for d in c.index], "y": [round(v, 0) for v in c.values],
                      "name": nombre, "type": "scatter", "mode": "lines", "yaxis": "y", "line": {"color": color}})
        dd = (c / c.cummax() - 1) * 100
        datos.append({"x": [d.strftime("%Y-%m-%d") for d in dd.index], "y": [round(v, 2) for v in dd.values],
                      "name": f"{nombre} (caída %)", "type": "scatter", "mode": "lines", "yaxis": "y2",
                      "showlegend": False, "line": {"width": 1, "color": color}})
    layout = {"title": titulo, "height": 520, "margin": {"l": 60, "r": 20, "t": 50, "b": 40},
              "yaxis": {"title": "Capital (EUR)", "domain": [0.35, 1]},
              "yaxis2": {"title": "Caída desde máximo (%)", "domain": [0, 0.28]},
              "legend": {"orientation": "h"}, "paper_bgcolor": "rgba(0,0,0,0)", "plot_bgcolor": "rgba(0,0,0,0)"}
    return (f'<div id="{div}" style="width:100%"></div>'
            f"<script>Plotly.newPlot('{div}',{json.dumps(datos)},{json.dumps(layout)},{{responsive:true}});</script>")


def _plotly_js() -> str:
    from plotly.offline import get_plotlyjs

    return get_plotlyjs()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rapido", action="store_true", help="omite la prueba de robustez")
    args = ap.parse_args()
    t0 = time.time()

    cfg = cargar_yaml("backtest.yaml")
    estr = cargar_yaml("estrategias.yaml")
    p_riesgo = cargar_yaml("riesgo.yaml")
    universo = cargar_universo()
    salida = RAIZ / cfg["carpeta_resultados"]
    salida.mkdir(parents=True, exist_ok=True)
    periodos = _periodos(cfg)

    m = cargar_mercado(universo, sma_regimen=estr["regimen"]["sma"])
    sen = calcular_senales(m, estr)
    usd = m.velas["EURUSD=X"]["close"]
    ref_total = m.velas[cfg["referencia_total"]]["close"]
    ref_total = (ref_total / usd.reindex(ref_total.index, method="ffill")).reindex(m.fechas, method="ffill")
    print(f"Datos: {len(m.simbolos)} activos, {m.fechas[0].date()} → {m.fechas[-1].date()} ({time.time()-t0:.0f}s)")

    secciones = []
    filas_total: dict[str, list[dict]] = {}
    curvas: dict[str, dict[str, pd.Series]] = {}
    resultados = {}
    for per, (desde, hasta) in periodos.items():
        filas_total[per] = []
        curvas[per] = {}
        for clave, usar in ESTRATEGIAS_RUN.items():
            res = simular(m, sen, estr, p_riesgo, desde, hasta, usar)
            resultados[(per, clave)] = res
            f = _fila(res, ref_total)
            f["nombre"] = NOMBRES[clave]
            filas_total[per].append(f)
            curvas[per][NOMBRES[clave]] = res.capital
            slug = "dentro" if per.startswith("Dentro") else "fuera"
            res.operaciones.to_csv(salida / f"operaciones_{slug}_{clave.replace('+', '')}.csv", index=False)
            print(f"{per:<18} {clave:<4} rent {f['cagr']:+.1%}  caída {f['max_caida']:.1%}  Sharpe {f['sharpe']:.2f}  "
                  f"ops {f['operaciones']}  ({time.time()-t0:.0f}s)")
        curvas[per]["Comprar y mantener SPY"] = inf.comprar_y_mantener(ref_total, res.capital, res.capital_inicial)

    # Por grupo: cartera dedicada a un solo grupo, con su referencia
    filas_grupo: dict[str, list[dict]] = {p: [] for p in periodos}
    for g in universo.grupos:
        mg = cargar_mercado(universo, grupos=[g], velas=m.velas, sma_regimen=estr["regimen"]["sma"])
        sg = calcular_senales(mg, estr)
        for per, (desde, hasta) in periodos.items():
            res = simular(mg, sg, estr, p_riesgo, desde, hasta, ("A", "B"))
            f = _fila(res, mg.referencias[g])
            f["nombre"] = f"{NOMBRE_GRUPO.get(g, g)} (ref. {universo.grupos[g].referencia})"
            filas_grupo[per].append(f)
        print(f"grupo {g} ({time.time()-t0:.0f}s)")

    # Desglose de operaciones de la cartera total por grupo (A+B)
    desglose: dict[str, list[dict]] = {}
    for per in periodos:
        ops = resultados[(per, "A+B")].operaciones
        filas = []
        for g, sub in (ops.groupby("grupo") if len(ops) else []):
            f = inf.metricas_operaciones(sub)
            f["nombre"] = NOMBRE_GRUPO.get(g, g)
            filas.append(f)
        for e, sub in (ops.groupby("estrategia") if len(ops) else []):
            f = inf.metricas_operaciones(sub)
            f["nombre"] = f"Señal {e}"
            filas.append(f)
        desglose[per] = filas

    # Robustez (dentro de muestra, A+B)
    filas_rob = []
    if not args.rapido:
        desde, hasta = periodos["Dentro de muestra"]
        base = next(f for f in filas_total["Dentro de muestra"] if f["nombre"] == NOMBRES["A+B"])
        filas_rob.append({**base, "nombre": "Valores actuales"})
        for sec, clave in cfg["robustez"]["parametros"]:
            for fac in cfg["robustez"]["factores"]:
                e2 = variar(estr, (sec, clave), fac)
                s2 = calcular_senales(m, e2)
                res = simular(m, s2, e2, p_riesgo, desde, hasta, ("A", "B"))
                f = _fila(res, ref_total)
                f["nombre"] = f"{sec}.{clave} = {e2[sec][clave]:g} (antes {estr[sec][clave]:g})"
                filas_rob.append(f)
                print(f"robustez {f['nombre']:<45} rent {f['cagr']:+.1%} Sharpe {f['sharpe']:.2f} ({time.time()-t0:.0f}s)")

    # Criterio de paso (fuera de muestra, cartera total A+B)
    fuera = next(f for f in filas_total["Fuera de muestra"] if f["nombre"] == NOMBRES["A+B"])
    ok, texto = inf.criterio(
        fuera, {"sharpe": fuera["ref_sharpe"]}, cfg["criterio"]["max_caida"], cfg["criterio"]["tolerancia_sharpe"])

    # ---- HTML ----
    res_fuera = resultados[("Fuera de muestra", "A+B")]
    desc = ", ".join(f"{k}: {v}" for k, v in sorted(res_fuera.descartes.items(), key=lambda x: -x[1])) or "ninguno"
    partes = [
        "<!doctype html><html lang='es'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>",
        "<title>Informe de backtest</title>",
        f"<script>{_plotly_js()}</script>",   # incrustado: el informe se abre sin conexión
        f"<style>{inf.ESTILO}</style></head><body>",
        "<h1>Backtest: alertas de trading swing</h1>",
        f"<p class='nota'>Capital inicial {p_riesgo['capital_eur']:,} EUR · costes de Trade Republic "
        f"(1 € por operación; cripto + 0,5 % de diferencial; acciones/ETFs + 0,1 %) · {len(m.simbolos)} activos · "
        f"datos {m.fechas[0].date()} a {m.fechas[-1].date()}. No es asesoramiento financiero.</p>",
        f"<h2>Criterio para pasar a alertas</h2><p class='{'ok' if ok else 'mal'}'>{'CUMPLE' if ok else 'NO CUMPLE'}</p>"
        f"<p>Fuera de muestra, cartera total A + B: {html.escape(texto)}.</p>",
    ]
    for per, (desde, hasta) in periodos.items():
        partes.append(f"<h2>{per} ({desde} a {hasta or 'hoy'})</h2>")
        partes.append(f"<p class='nota'>Cartera total. Referencia: comprar y mantener {cfg['referencia_total']} (en EUR).</p>")
        partes.append(f"<div class='tabla'>{inf.tabla_html(filas_total[per], 'nombre')}</div>")
        partes.append(_grafico(curvas[per], f"Evolución del capital · {per}", f"g{len(partes)}"))
        partes.append("<h3>Operaciones de la cartera total A + B, por grupo y por señal</h3>")
        cols_ops = [c for c in inf.COLUMNAS if c[0] in ("operaciones", "aciertos", "ganancia_media", "perdida_media",
                                                         "duracion_media_dias", "costes_eur")]
        cols_ops.insert(1, ("resultado_eur", "Resultado", "eur"))
        partes.append(f"<div class='tabla'>{inf.tabla_html(desglose[per], 'nombre', cols_ops)}</div>")
        partes.append("<h3>Cada grupo por separado (cartera de 10.000 € solo con ese grupo, A + B)</h3>")
        partes.append(f"<div class='tabla'>{inf.tabla_html(filas_grupo[per], 'nombre')}</div>")
    if filas_rob:
        cols_rob = [c for c in inf.COLUMNAS if c[0] in ("cagr", "max_caida", "sharpe", "final", "operaciones", "aciertos")]
        partes.append("<h2>Robustez (dentro de muestra, A + B, cada parámetro ±20 %)</h2>")
        partes.append("<p class='nota'>Si el resultado se hunde con cambios pequeños, la estrategia está sobreajustada.</p>")
        partes.append(f"<div class='tabla'>{inf.tabla_html(filas_rob, 'nombre', cols_rob)}</div>")
    partes.append(f"<h2>Notas</h2><ul>"
                  f"<li>Señales descartadas fuera de muestra (A + B): {html.escape(desc)}.</li>"
                  f"<li>Freno por caída activado fuera de muestra: {len(res_fuera.pausas)} veces.</li>"
                  "<li>Sesgo de supervivencia: se usa la lista actual de empresas, lo que infla los resultados.</li>"
                  "<li>Las señales se calculan con el cierre del día y se ejecutan en la apertura siguiente; los stops, "
                  "al precio del stop o a la apertura si el precio abre por debajo.</li>"
                  "<li>Las posiciones abiertas al final del periodo se valoran al último cierre.</li></ul>")
    partes.append("</body></html>")
    (salida / "informe.html").write_text("\n".join(partes), encoding="utf-8")
    resumen = {"criterio_ok": ok, "criterio": texto, "total": filas_total, "grupos": filas_grupo, "robustez": filas_rob}
    (salida / "resumen.json").write_text(json.dumps(resumen, default=str, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"\nCriterio: {'CUMPLE' if ok else 'NO CUMPLE'} · {texto}")
    print(f"Informe: {salida / 'informe.html'} ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
