"""Flujo diario (SPEC §7). Uso:

    python -m src.main --dry-run           # no envía email: imprime el resultado
    python -m src.main                     # envía el email (lo usa GitHub Actions)
    python -m src.main --dry-run --sin-descarga --html email.html

Nunca envía órdenes a ningún bróker.

Modo papel: la cartera es simulada con el mismo motor que el backtest, desde
`fecha_inicio_papel` (config/alertas.yaml) hasta la última vela cerrada. Las órdenes
que quedan pendientes al final son exactamente lo que el email pide hacer hoy.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from backtest.motor import Mercado, Resultado, calcular_senales, cargar_mercado, simular
from src import alertas, contexto_ia
from src.alertas import Cerrada, Compra, Informe, Posicion, Venta
from src.config import RAIZ, Universo, cargar_universo, cargar_yaml
from src.estrategias import ESTRATEGIAS, PARAMS

ZONA = ZoneInfo("Europe/Amsterdam")


def resultados_proximos(simbolo: str, hoy: date, dias_habiles: int) -> str | None:
    """Fecha de resultados trimestrales si cae en los próximos N días hábiles (Yahoo).
    Cualquier fallo → None (es solo un aviso)."""
    try:
        import logging

        import yfinance as yf

        logging.getLogger("yfinance").setLevel(logging.CRITICAL)
        cal = yf.Ticker(simbolo).calendar
        fechas = cal.get("Earnings Date") if isinstance(cal, dict) else None
        if not fechas:
            return None
        limite = np.busday_offset(np.datetime64(hoy), dias_habiles, roll="forward").astype(object)
        for f in fechas:
            f = pd.Timestamp(f).date()
            if hoy <= f <= limite:
                return f.strftime("%d-%m-%Y")
    except Exception:
        return None
    return None


def construir_informe(
    m: Mercado,
    res: Resultado,
    universo: Universo,
    estr: dict,
    p_riesgo: dict,
    cfg: dict,
    hoy: date,
    avisos: list[str],
) -> Informe:
    nombres = {a.simbolo: a.nombre for a in universo.activos()}
    monedas = {a.simbolo: a.moneda for a in universo.activos()}
    ultimo = len(m.fechas) - 1

    def ultimo_valor(j: int) -> tuple[float, float]:
        col = m.close[:, j]
        k = np.flatnonzero(~np.isnan(col))[-1]
        return float(col[k]), float(m.fx[k, j])

    regimen = {g: bool(v[ultimo]) for g, v in m.regimen.items()}
    inf = Informe(fecha=hoy.strftime("%d-%m-%Y"), regimen=regimen, modo=cfg.get("modo", "papel"),
                  capital_inicial=res.capital_inicial, fecha_inicio=pd.Timestamp(cfg["fecha_inicio_papel"]).strftime("%d-%m-%Y"),
                  referencia=cfg.get("referencia_backtest", ""))

    for p in res.posiciones:
        s = m.simbolos[p.j]
        c, fx = ultimo_valor(p.j)
        if p.salida_pendiente:
            inf.ventas.append(Venta(s, nombres.get(s, s), m.grupo[p.j], p.unidades, p.salida_pendiente,
                                    p.entrada / p.fx_entrada, c / fx, bool(m.cripto[p.j])))
        subido = not np.isnan(p.stop_previo) and p.stop > p.stop_previo + 1e-9
        inf.posiciones.append(Posicion(s, nombres.get(s, s), m.grupo[p.j], p.estrategia,
                                       p.fecha_entrada.strftime("%d-%m-%Y"), p.unidades, p.entrada / p.fx_entrada,
                                       c / fx, p.stop / fx, subido, p.sesiones, bool(m.cripto[p.j])))

    for o in res.compras:
        s = m.simbolos[o.j]
        c, fx = ultimo_valor(o.j)
        g = "A" if "A" in o.estrategia else "B"
        stop = ESTRATEGIAS[g].stop_inicial(c, o.atr, estr[PARAMS[g]])
        inf.compras.append(Compra(s, nombres.get(s, s), m.grupo[o.j], o.estrategia, o.unidades, c / fx,
                                  o.unidades * c / fx, stop / fx, o.unidades * (c - stop) / fx, bool(m.cripto[o.j]),
                                  stop_nativo=stop, moneda=monedas.get(s, "EUR")))
    # Prioridad del email: compras por importe (las mismas que eligió el motor por momentum)
    if len(res.capital):
        inf.capital = float(res.capital.iloc[-1])
        inf.efectivo = inf.capital - sum(p.unidades * p.ultimo_eur for p in inf.posiciones)
    else:
        inf.capital = inf.efectivo = res.capital_inicial

    ops = res.operaciones
    if len(ops):
        inf.operaciones_cerradas = len(ops)
        inf.operaciones_ganadoras = int((ops["resultado_eur"] > 0).sum())
        ult = ops[ops["fecha_salida"] == m.fechas[ultimo]]
        for _, o in ult.iterrows():
            inf.cerradas.append(Cerrada(o["activo"], nombres.get(o["activo"], o["activo"]), o["motivo_salida"],
                                        float(o["resultado_eur"]), float(o["rentabilidad"])))

    for g, ok in regimen.items():
        if not ok:
            inf.avisos.append(f"{alertas.GRUPOS.get(g, g)} en régimen bajista: sin compras nuevas en ese grupo.")
    if res.en_pausa:
        inf.avisos.append(f"Freno por caída activo: la cuenta cayó un {p_riesgo['freno_caida']:.0%} desde su máximo; "
                          "se pausan las compras unas semanas.")
    if res.descartes_ultimo_dia:
        lista = ", ".join(f"{s} ({mot})" for s, mot in res.descartes_ultimo_dia[:10])
        n = len(res.descartes_ultimo_dia)
        inf.avisos.append(f"{n} señal{'es' if n != 1 else ''} descartada{'s' if n != 1 else ''}: {lista}.")
    inf.avisos.extend(avisos)
    return inf


def ejecutar(
    dry_run: bool = False,
    sin_descarga: bool = False,
    forzar: bool = False,
    ahora: datetime | None = None,
    salida_html: Path | None = None,
    fecha_inicio: str | None = None,
) -> Informe | None:
    cfg = cargar_yaml("alertas.yaml")
    if fecha_inicio:
        cfg["fecha_inicio_papel"] = fecha_inicio
    ahora = (ahora or datetime.now(timezone.utc)).astimezone(ZONA)
    hoy = ahora.date()
    marca = RAIZ / cfg["ultimo_envio"]

    if not dry_run and not forzar:
        h, mi = map(int, cfg["hora_envio"].split(":"))
        if (ahora.hour, ahora.minute) < (h, mi):
            print(f"Aún no son las {cfg['hora_envio']} en Ámsterdam ({ahora:%H:%M}); no se envía.")
            return None
        if marca.exists() and marca.read_text().strip() == hoy.isoformat():
            print("El email de hoy ya se envió.")
            return None

    avisos: list[str] = []
    excluir: set[str] = set()
    if not sin_descarga:
        from src.datos.actualizar import ejecutar as actualizar_datos

        informe_datos = actualizar_datos(ahora=ahora)
    else:
        ruta = RAIZ / cargar_yaml("datos.yaml")["carpeta_cache"] / "informe_validacion.csv"
        informe_datos = pd.read_csv(ruta) if ruta.exists() else pd.DataFrame()
    if len(informe_datos):
        malos = informe_datos[~informe_datos["apto"].astype(bool)]
        excluir = set(malos["simbolo"])
        for _, f in malos.iterrows():
            avisos.append(f"Datos: {f['simbolo']} excluido hoy ({str(f['detalle'])[:120]}).")
    if not avisos:
        avisos.append("Datos: sin incidencias.")

    estr = cargar_yaml("estrategias.yaml")
    p_riesgo = cargar_yaml("riesgo.yaml")
    universo = cargar_universo()
    m = cargar_mercado(universo, sma_regimen=estr["regimen"]["sma"])
    sen = calcular_senales(m, estr)
    res = simular(m, sen, estr, p_riesgo, desde=cfg["fecha_inicio_papel"], cerrar_al_final=False,
                  excluir_compras_ultimo_dia=frozenset(excluir))
    inf = construir_informe(m, res, universo, estr, p_riesgo, cfg, hoy, avisos)

    # Resultados trimestrales próximos (solo acciones)
    for x in [*inf.compras, *inf.posiciones]:
        if x.grupo in ("eeuu", "europa"):
            x.resultados = resultados_proximos(x.simbolo, hoy, int(cfg.get("resultados_dias_habiles", 3)))

    # Contexto de noticias (una sola llamada a la IA)
    peticiones = [contexto_ia.Peticion(c.simbolo, c.nombre, "señal de compra") for c in inf.compras]
    peticiones += [contexto_ia.Peticion(p.simbolo, p.nombre, f"posición abierta, {alertas.pct(p.rentabilidad)}")
                   for p in inf.posiciones]
    ctx, aviso = contexto_ia.obtener(peticiones, hoy.isoformat(), cfg.get("contexto_ia", {}))
    for x in [*inf.compras, *inf.posiciones]:
        x.contexto = ctx.get(x.simbolo)
    if aviso:
        inf.avisos.append(aviso)

    if salida_html:
        Path(salida_html).write_text(alertas.html_email(inf), encoding="utf-8")
    print(alertas.asunto(inf))
    print()
    print(alertas.texto(inf))
    if dry_run:
        return inf

    alertas.enviar(inf)
    n = alertas.guardar_historial(inf, RAIZ / cfg["historial"])
    marca.parent.mkdir(parents=True, exist_ok=True)
    marca.write_text(hoy.isoformat())
    print(f"\nEmail enviado. {n} filas añadidas al historial.")
    return inf


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="no envía email; imprime el resultado")
    ap.add_argument("--sin-descarga", action="store_true", help="usa la caché sin descargar datos nuevos")
    ap.add_argument("--forzar", action="store_true", help="envía aunque no sea la hora o ya se haya enviado hoy")
    ap.add_argument("--html", type=Path, help="guarda la versión HTML del email en este archivo")
    ap.add_argument("--inicio", help="fecha de inicio de la cartera de papel (prueba)")
    a = ap.parse_args()
    ejecutar(a.dry_run, a.sin_descarga, a.forzar, salida_html=a.html, fecha_inicio=a.inicio)


if __name__ == "__main__":
    sys.exit(main())
