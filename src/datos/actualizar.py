"""Descarga, cachea y valida todo el universo. Uso:

    python -m src.datos.actualizar                 # todo el universo
    python -m src.datos.actualizar --grupos cripto # solo un grupo
    python -m src.datos.actualizar --muestra ASML.AS

Escribe un informe por activo en <carpeta_cache>/informe_validacion.csv.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

from src.config import RAIZ, Activo, Grupo, Universo, cargar_universo, cargar_yaml
from src.datos.cache import CacheParquet, actualizar
from src.datos.calendario import ultima_vela_cerrada
from src.datos.cripto import CcxtProvider
from src.datos.proveedor import DataProvider, ErrorDatos
from src.datos.validacion import ERROR, Incidencia, ResultadoValidacion, validar
from src.datos.yahoo import YahooProvider


@dataclass
class Tarea:
    simbolo: str
    grupo: Grupo
    proveedor: str
    simbolo_historia: str | None = None
    uso: str = "activo"


def tareas(universo: Universo, grupos: list[str] | None = None) -> list[Tarea]:
    out = []
    for g in universo.grupos.values():
        if grupos and g.clave not in grupos:
            continue
        for a in g.activos:
            out.append(Tarea(a.simbolo, g, a.proveedor, a.simbolo_historia))
    for aux in universo.auxiliares:
        g = universo.grupos[aux["grupo_calendario"]]
        if grupos and g.clave not in grupos:
            continue
        if aux["simbolo"] not in {t.simbolo for t in out}:
            out.append(Tarea(aux["simbolo"], g, aux["proveedor"], uso=aux["uso"]))
    return out


def ejecutar(
    grupos: list[str] | None = None,
    ahora: datetime | None = None,
    proveedores: dict[str, DataProvider] | None = None,
    carpeta_config: Path | None = None,
    carpeta_cache: Path | None = None,
) -> pd.DataFrame:
    cfg = cargar_yaml("datos.yaml", carpeta_config) if carpeta_config else cargar_yaml("datos.yaml")
    universo = cargar_universo(carpeta_config) if carpeta_config else cargar_universo()
    ahora = ahora or datetime.now(timezone.utc)
    carpeta_cache = Path(carpeta_cache) if carpeta_cache else RAIZ / cfg["carpeta_cache"]
    cache = CacheParquet(carpeta_cache)
    proveedores = proveedores or {
        "yahoo": YahooProvider(),
        cfg["cripto"]["exchange"]: CcxtProvider(cfg["cripto"]["exchange"], cfg["cripto"]["limite_velas_por_peticion"]),
    }
    respaldo = proveedores.get(cfg["cripto"]["historia_respaldo"])
    filas = []
    for t in tareas(universo, grupos):
        hasta = ultima_vela_cerrada(
            ahora, t.grupo.hora_corte, cfg["zona_horaria"], t.grupo.desfase_dias,
            solo_dias_habiles=not t.grupo.es_cripto,
        )
        desde_inicial = date(hasta.year - cfg["anios_historia"], hasta.month, 1)
        prov = proveedores[t.proveedor]
        es_cripto = t.proveedor != "yahoo"
        try:
            res = actualizar(
                cache, prov, t.simbolo, hasta, desde_inicial,
                cfg["actualizacion"]["dias_solape"], cfg["actualizacion"]["tolerancia_ajuste"],
                respaldo=respaldo if es_cripto else None,
                simbolo_respaldo=t.simbolo_historia if es_cripto else None,
            )
            datos, accion, detalle_act = res.datos, res.accion, res.detalle
        except ErrorDatos as e:
            datos, accion, detalle_act = None, "fallo_descarga", str(e)
        val = validar(t.simbolo, datos, hasta, cfg["validacion"], diario=es_cripto) if datos is not None else \
            ResultadoValidacion(t.simbolo, [Incidencia(ERROR, "descarga", detalle_act)])
        filas.append({
            "simbolo": t.simbolo,
            "grupo": t.grupo.clave,
            "uso": t.uso,
            "apto": val.apto,
            "velas": 0 if datos is None else len(datos),
            "desde": None if datos is None or datos.empty else datos.index.min().date(),
            "hasta": None if datos is None or datos.empty else datos.index.max().date(),
            "esperada": hasta,
            "accion": accion,
            "errores": len(val.errores),
            "avisos": len(val.avisos),
            "detalle": " | ".join(str(i) for i in val.errores[:3] + val.avisos[:3]) or detalle_act,
        })
        print(f"{'OK ' if val.apto else 'XX '} {t.simbolo:<12} {accion:<18} {filas[-1]['velas']:>5} velas"
              + ("" if val.apto else f"  {val.errores[0]}"))
    informe = pd.DataFrame(filas)
    carpeta_cache.mkdir(parents=True, exist_ok=True)
    informe.to_csv(carpeta_cache / "informe_validacion.csv", index=False)
    return informe


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--grupos", help="lista separada por comas: eeuu,europa,etfs,cripto")
    ap.add_argument("--muestra", help="símbolo del que imprimir las últimas velas con indicadores")
    args = ap.parse_args()
    informe = ejecutar(args.grupos.split(",") if args.grupos else None)
    print()
    print(informe.groupby("grupo")["apto"].agg(total="count", aptos="sum").to_string())
    print(f"\nTotal: {int(informe['apto'].sum())}/{len(informe)} aptos")
    if args.muestra:
        from src.indicadores import tabla_indicadores

        cfg = cargar_yaml("datos.yaml")
        df = CacheParquet(RAIZ / cfg["carpeta_cache"]).leer(args.muestra)
        if df is None:
            print(f"{args.muestra}: sin datos en caché")
        else:
            print(f"\nMuestra {args.muestra}:\n{tabla_indicadores(df, cargar_yaml('estrategias.yaml')).tail(10).round(2).to_string()}")


if __name__ == "__main__":
    main()
