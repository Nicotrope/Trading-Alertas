"""Simulación de cartera completa (SPEC §5).

Usa el mismo código de señales (src/estrategias) y de riesgo (src/riesgo.py) que
usará el sistema diario.

Cronología de cada día d del calendario (unión de todos los mercados):
1. Apertura: se ejecutan las órdenes pendientes (primero ventas, luego compras) de los
   activos que cotizan ese día, al precio de apertura con deslizamiento en contra.
2. Durante la sesión: si el mínimo del día toca el stop, la posición se cierra al stop
   (o a la apertura, si abrió ya por debajo: hueco).
3. Cierre: se actualizan stops dinámicos y se evalúan salidas por regla o tiempo (se
   venden en la apertura siguiente); se calcula el capital; se evalúan compras nuevas con
   el cierre de d, que se ejecutarán en la siguiente apertura de ese activo.

Ninguna decisión del día d usa datos posteriores a d (ver tests/test_backtest.py).
"""
from __future__ import annotations

import copy
import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from src import indicadores as ind
from src import riesgo
from src.config import RAIZ, Universo, cargar_universo, cargar_yaml
from src.datos.cache import CacheParquet
from src.estrategias import ESTRATEGIAS, PARAMS, regimen

DIVISA = "EURUSD=X"   # dólares por euro


# ---------------------------------------------------------------------------
# Preparación de datos
# ---------------------------------------------------------------------------

def limpiar(df: pd.DataFrame) -> pd.DataFrame:
    """Quita velas sin precio y corrige velas incoherentes (high/low que no contienen
    open/close, visto en velas antiguas de cripto en Yahoo)."""
    df = df[["open", "high", "low", "close"]].astype(float).dropna()
    df = df[(df > 0).all(axis=1)].copy()
    oc_max = df[["open", "close"]].max(axis=1)
    oc_min = df[["open", "close"]].min(axis=1)
    df["high"] = np.maximum(df["high"], oc_max)
    df["low"] = np.minimum(df["low"], oc_min)
    return df


@dataclass
class Mercado:
    """Matrices alineadas en un calendario común (filas = días, columnas = activos)."""
    fechas: pd.DatetimeIndex
    simbolos: list[str]
    grupo: list[str]
    sector: list[str]
    cripto: np.ndarray            # bool por activo
    hay: np.ndarray               # bool [día, activo]: el activo tiene vela ese día
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    fx: np.ndarray                # divisor para pasar a EUR (1 para activos en EUR)
    regimen: dict[str, np.ndarray]  # grupo -> bool por día
    referencias: dict[str, pd.Series]  # grupo -> cierre de la referencia en EUR
    velas: dict[str, pd.DataFrame]     # velas limpias por símbolo (para recalcular señales)


def cargar_mercado(
    universo: Universo | None = None,
    carpeta_cache: Path | None = None,
    grupos: list[str] | None = None,
    velas: dict[str, pd.DataFrame] | None = None,
    sma_regimen: int = 200,
) -> Mercado:
    """Lee la caché y construye las matrices. `velas` permite inyectar datos (tests)."""
    universo = universo or cargar_universo()
    if velas is None:
        cfg = cargar_yaml("datos.yaml")
        cache = CacheParquet(carpeta_cache or RAIZ / cfg["carpeta_cache"])
        simbolos_todos = [a.simbolo for a in universo.activos()] + [x["simbolo"] for x in universo.auxiliares]
        velas = {}
        for s in simbolos_todos:
            df = cache.leer(s)
            if df is not None and not df.empty:
                velas[s] = limpiar(df)
    activos = [a for a in universo.activos() if (not grupos or a.grupo in grupos) and a.simbolo in velas]
    fechas = pd.DatetimeIndex(sorted(set().union(*[velas[a.simbolo].index for a in activos])), name="fecha")

    eurusd = velas.get(DIVISA)
    fx_usd = eurusd["close"].reindex(fechas, method="ffill") if eurusd is not None else None

    def matriz(col: str) -> np.ndarray:
        return np.column_stack([velas[a.simbolo][col].reindex(fechas).to_numpy() for a in activos])

    fx = np.ones((len(fechas), len(activos)))
    for j, a in enumerate(activos):
        if a.moneda == "USD":
            if fx_usd is None:
                raise ValueError("falta EURUSD=X para convertir activos en USD")
            fx[:, j] = fx_usd.bfill().to_numpy()

    reg, refs = {}, {}
    for clave, g in universo.grupos.items():
        if grupos and clave not in grupos:
            continue
        ref = velas.get(g.referencia)
        if ref is None:
            reg[clave] = np.zeros(len(fechas), bool)
            continue
        alc = regimen.alcista(ref, sma_regimen)
        reg[clave] = alc.reindex(fechas, method="ffill").fillna(False).to_numpy(bool)
        c = ref["close"].reindex(fechas, method="ffill")
        if g.referencia in (DIVISA,) or g.referencia.startswith("^STOXX") or "/" in g.referencia:
            refs[clave] = c
        else:  # SPY cotiza en USD
            refs[clave] = c / fx_usd if fx_usd is not None else c

    cl = matriz("close")
    return Mercado(
        fechas=fechas,
        simbolos=[a.simbolo for a in activos],
        grupo=[a.grupo for a in activos],
        sector=[a.sector for a in activos],
        cripto=np.array([universo.grupos[a.grupo].es_cripto for a in activos]),
        hay=~np.isnan(cl),
        open=matriz("open"), high=matriz("high"), low=matriz("low"), close=cl,
        fx=fx, regimen=reg, referencias=refs, velas=velas,
    )


@dataclass
class Senales:
    entrada: dict[str, np.ndarray]   # estrategia -> bool [día, activo]
    salida: dict[str, np.ndarray]
    atr: np.ndarray
    momentum: np.ndarray


def calcular_senales(m: Mercado, estrategias: dict) -> Senales:
    p_ind = estrategias["indicadores"]
    ent = {k: np.zeros(m.close.shape, bool) for k in ESTRATEGIAS}
    sal = {k: np.zeros(m.close.shape, bool) for k in ESTRATEGIAS}
    atr = np.full(m.close.shape, np.nan)
    mom = np.full(m.close.shape, np.nan)
    for j, s in enumerate(m.simbolos):
        df = m.velas[s]
        for k, mod in ESTRATEGIAS.items():
            sen = mod.senales(df, estrategias[PARAMS[k]], p_ind).reindex(m.fechas)
            ent[k][:, j] = sen["entrada"].fillna(False).to_numpy(bool)
            sal[k][:, j] = sen["salida"].fillna(False).to_numpy(bool)
            if k == "A":
                atr[:, j] = sen["atr"].to_numpy(float)
        mom[:, j] = ind.rentabilidad(df["close"], p_ind["momentum_sesiones"]).reindex(m.fechas).to_numpy(float)
    return Senales(ent, sal, atr, mom)


# ---------------------------------------------------------------------------
# Simulación
# ---------------------------------------------------------------------------

@dataclass
class Posicion:
    j: int
    estrategia: str          # "A", "B" o "A+B" (coincidieron; se gestiona con las reglas de A)
    fecha_entrada: pd.Timestamp
    entrada: float           # precio de ejecución, moneda del activo
    unidades: float
    stop: float              # moneda del activo
    stop_inicial: float
    fx_entrada: float
    coste_entrada: float     # comisión de compra, EUR
    max_cierre: float
    sesiones: int = 0
    salida_pendiente: str | None = None


@dataclass
class OrdenCompra:
    j: int
    estrategia: str
    unidades: float
    atr: float
    fecha_senal: pd.Timestamp


@dataclass
class Resultado:
    capital: pd.Series                 # capital diario en EUR
    operaciones: pd.DataFrame
    descartes: dict[str, int]
    capital_inicial: float
    pausas: list[pd.Timestamp] = field(default_factory=list)


def _gestion(estrategia: str) -> str:
    return "A" if "A" in estrategia else "B"


def simular(
    m: Mercado,
    sen: Senales,
    estrategias: dict,
    p_riesgo: dict,
    desde: str | pd.Timestamp | None = None,
    hasta: str | pd.Timestamp | None = None,
    usar: tuple[str, ...] = ("A", "B"),
) -> Resultado:
    costes = p_riesgo["costes"]
    capital0 = float(p_riesgo["capital_eur"])
    efectivo = capital0
    pos: dict[int, Posicion] = {}
    pendientes: dict[int, OrdenCompra] = {}
    filas_ops: list[dict] = []
    descartes: dict[str, int] = {}
    pausas: list[pd.Timestamp] = []
    curva = []
    pico = capital0
    pausa_restante = 0

    dias = np.arange(len(m.fechas))
    if desde is not None:
        dias = dias[m.fechas[dias] >= pd.Timestamp(desde)]
    if hasta is not None:
        dias = dias[m.fechas[dias] <= pd.Timestamp(hasta)]

    ultimo_cierre = np.full(len(m.simbolos), np.nan)
    ultimo_fx = np.ones(len(m.simbolos))
    # precios conocidos antes del inicio del periodo (para valorar posiciones)
    if len(dias):
        previo = m.close[: dias[0]]
        for j in range(len(m.simbolos)):
            v = previo[:, j][~np.isnan(previo[:, j])]
            if len(v):
                ultimo_cierre[j] = v[-1]

    def cerrar(p: Posicion, i: int, precio_bruto: float, motivo: str) -> None:
        nonlocal efectivo
        es_c = bool(m.cripto[p.j])
        precio = precio_bruto * (1 - riesgo.deslizamiento(es_c, costes))
        fx = m.fx[i, p.j]
        bruto = p.unidades * precio / fx
        com = riesgo.coste_operacion(bruto, es_c, costes)
        efectivo += bruto - com
        invertido = p.unidades * p.entrada / p.fx_entrada
        pnl = bruto - com - invertido - p.coste_entrada
        filas_ops.append({
            "activo": m.simbolos[p.j], "grupo": m.grupo[p.j], "sector": m.sector[p.j],
            "estrategia": p.estrategia, "fecha_entrada": p.fecha_entrada, "fecha_salida": m.fechas[i],
            "precio_entrada": p.entrada, "precio_salida": precio, "unidades": p.unidades,
            "stop_inicial": p.stop_inicial, "importe_eur": invertido, "resultado_eur": pnl,
            "rentabilidad": pnl / invertido, "r_multiple": pnl / max(p.unidades * (p.entrada - p.stop_inicial) / p.fx_entrada, 1e-9),
            "sesiones": p.sesiones, "dias": (m.fechas[i] - p.fecha_entrada).days, "motivo_salida": motivo,
            "costes_eur": p.coste_entrada + com + p.unidades * (p.entrada * costes_desl(es_c) / p.fx_entrada + precio_bruto * costes_desl(es_c) / fx),
        })
        del pos[p.j]

    def costes_desl(es_c: bool) -> float:
        return riesgo.deslizamiento(es_c, costes)

    for i in dias:
        hoy = m.fechas[i]
        hay = m.hay[i]

        # 1. Apertura: ventas pendientes, después compras pendientes
        for j in [j for j, p in pos.items() if p.salida_pendiente and hay[j]]:
            cerrar(pos[j], i, m.open[i, j], pos[j].salida_pendiente)
        for j in [j for j in pendientes if hay[j]]:
            o = pendientes.pop(j)
            es_c = bool(m.cripto[j])
            fill = m.open[i, j] * (1 + riesgo.deslizamiento(es_c, costes))
            fx = m.fx[i, j]
            mod = ESTRATEGIAS[_gestion(o.estrategia)]
            stop = mod.stop_inicial(fill, o.atr, estrategias[PARAMS[_gestion(o.estrategia)]])
            unidades = o.unidades
            importe = unidades * fill / fx
            com = riesgo.coste_operacion(importe, es_c, costes)
            if importe + com > efectivo:   # la apertura subió: se compra lo que alcance
                unidades = riesgo.redondear_unidades((efectivo - com) / (fill / fx), es_c)
                importe = unidades * fill / fx
                com = riesgo.coste_operacion(importe, es_c, costes)
            if importe < p_riesgo["tamano_minimo_eur"] or stop >= fill:
                descartes[riesgo.SIN_LIQUIDEZ] = descartes.get(riesgo.SIN_LIQUIDEZ, 0) + 1
                continue
            efectivo -= importe + com
            pos[j] = Posicion(j, o.estrategia, hoy, fill, unidades, stop, stop, fx, com, max_cierre=fill)

        # 2. Sesión: stops
        for j in [j for j, p in pos.items() if hay[j] and m.low[i, j] <= p.stop]:
            p = pos[j]
            cerrar(p, i, min(m.open[i, j], p.stop), "stop" if p.stop <= p.stop_inicial else "stop dinámico")

        # 3. Cierre: gestión de posiciones abiertas
        for j, p in pos.items():
            if not hay[j]:
                continue
            p.sesiones += 1
            p.max_cierre = max(p.max_cierre, m.close[i, j])
            g = _gestion(p.estrategia)
            mod, par = ESTRATEGIAS[g], estrategias[PARAMS[g]]
            if not math.isnan(sen.atr[i, j]):
                p.stop = mod.stop_dinamico(p.stop, p.max_cierre, sen.atr[i, j], par)
            if p.salida_pendiente:
                continue
            if sen.salida[g][i, j]:
                p.salida_pendiente = f"regla {g}"
            elif mod.sesiones_maximas(par) and p.sesiones >= mod.sesiones_maximas(par):
                p.salida_pendiente = "tiempo"

        ultimo_cierre[hay] = m.close[i, hay]
        ultimo_fx[hay] = m.fx[i, hay]
        valor = {j: p.unidades * ultimo_cierre[j] / ultimo_fx[j] for j, p in pos.items()}
        capital = efectivo + sum(valor.values())
        curva.append(capital)

        # Freno por caída
        if pausa_restante > 0:
            if hoy.weekday() < 5:
                pausa_restante -= 1
            if pausa_restante == 0:
                pico = capital
        else:
            pico = max(pico, capital)
            if capital <= pico * (1 - p_riesgo["freno_caida"]):
                pausa_restante = int(p_riesgo.get("freno_pausa_sesiones", 20))
                pausas.append(hoy)

        # 3b. Compras nuevas (señal al cierre de hoy, ejecución en la próxima apertura)
        cand = np.zeros(len(m.simbolos), bool)
        for k in usar:
            cand |= sen.entrada[k][i]
        cand &= hay
        if not cand.any():
            continue
        cand_js = [j for j in np.flatnonzero(cand)
                   if m.regimen.get(m.grupo[j], np.zeros(1, bool))[i] and j not in pos and j not in pendientes]
        if not cand_js:
            continue
        if pausa_restante > 0:
            descartes[riesgo.FRENO] = descartes.get(riesgo.FRENO, 0) + len(cand_js)
            continue
        cand_js.sort(key=lambda j: -sen.momentum[i, j] if not math.isnan(sen.momentum[i, j]) else math.inf)

        vivas = [j for j, p in pos.items() if not p.salida_pendiente]
        libre = efectivo + sum(valor[j] for j, p in pos.items() if p.salida_pendiente)
        reservado = 0.0
        for j in pendientes:  # ya ocupan hueco, sector y efectivo
            vivas.append(j)
            reservado += pendientes[j].unidades * m.close[i, j] / m.fx[i, j] if hay[j] else 0.0
        expo_cripto = sum(valor[j] for j in vivas if j in valor and m.cripto[j])
        expo_cripto += sum(pendientes[j].unidades * ultimo_cierre[j] / ultimo_fx[j] for j in pendientes if m.cripto[j])

        for j in cand_js:
            def descartar(motivo: str) -> None:
                descartes[motivo] = descartes.get(motivo, 0) + 1
            if len(vivas) >= p_riesgo["posiciones_maximas"]:
                descartar(riesgo.SIN_HUECO)
                continue
            if sum(1 for v in vivas if m.sector[v] == m.sector[j]) >= p_riesgo["posiciones_maximas_por_sector"]:
                descartar(riesgo.LIMITE_SECTOR)
                continue
            es_a = "A" in usar and sen.entrada["A"][i, j]
            es_b = "B" in usar and sen.entrada["B"][i, j]
            estr = "A+B" if es_a and es_b else ("A" if es_a else "B")
            g = _gestion(estr)
            atr = sen.atr[i, j]
            if math.isnan(atr) or atr <= 0:
                continue
            c = m.close[i, j]
            stop = ESTRATEGIAS[g].stop_inicial(c, atr, estrategias[PARAMS[g]])
            fx = m.fx[i, j]
            prop = riesgo.tamano(capital, c / fx, stop / fx, bool(m.cripto[j]), p_riesgo,
                                 efectivo_eur=libre - reservado, exposicion_cripto_eur=expo_cripto)
            if prop.motivo:
                descartar(prop.motivo)
                continue
            pendientes[j] = OrdenCompra(j, estr, prop.unidades, atr, hoy)
            vivas.append(j)
            reservado += prop.importe_eur * 1.01
            if m.cripto[j]:
                expo_cripto += prop.importe_eur

    # Fin del periodo: las posiciones abiertas se valoran al último cierre
    if len(dias):
        ult = dias[-1]
        for j in list(pos):
            p = pos[j]
            cerrar_sin_coste = ultimo_cierre[j] / (1 - riesgo.deslizamiento(bool(m.cripto[j]), costes))
            cerrar(p, ult, cerrar_sin_coste, "abierta al final")

    ops = pd.DataFrame(filas_ops)
    return Resultado(pd.Series(curva, index=m.fechas[dias], name="capital"), ops, descartes, capital0, pausas)


def variar(estrategias: dict, ruta: tuple[str, str], factor: float) -> dict:
    """Copia de los parámetros con uno multiplicado por `factor` (enteros redondeados)."""
    nuevo = copy.deepcopy(estrategias)
    sec, clave = ruta
    v = nuevo[sec][clave]
    nuevo[sec][clave] = max(1, round(v * factor)) if isinstance(v, int) else v * factor
    return nuevo
