"""Carga de la configuración YAML de config/."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

RAIZ = Path(__file__).resolve().parent.parent
CARPETA_CONFIG = RAIZ / "config"


def cargar_yaml(nombre: str, carpeta: Path = CARPETA_CONFIG) -> dict[str, Any]:
    with open(carpeta / nombre, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


@dataclass(frozen=True)
class Activo:
    simbolo: str
    nombre: str
    sector: str
    grupo: str
    proveedor: str
    moneda: str
    simbolo_historia: str | None = None


@dataclass(frozen=True)
class Grupo:
    clave: str
    nombre: str
    proveedor: str
    moneda: str
    referencia: str
    hora_corte: str
    desfase_dias: int = 0
    activos: tuple[Activo, ...] = field(default_factory=tuple)

    @property
    def es_cripto(self) -> bool:
        return self.proveedor != "yahoo"


@dataclass(frozen=True)
class Universo:
    grupos: dict[str, Grupo]
    auxiliares: tuple[dict[str, Any], ...]

    def activos(self) -> list[Activo]:
        return [a for g in self.grupos.values() for a in g.activos]


def cargar_universo(carpeta: Path = CARPETA_CONFIG) -> Universo:
    crudo = cargar_yaml("universo.yaml", carpeta)
    grupos: dict[str, Grupo] = {}
    vistos: set[str] = set()
    for clave, g in crudo["grupos"].items():
        activos = []
        for a in g["activos"]:
            if a["simbolo"] in vistos:
                raise ValueError(f"Activo duplicado en universo.yaml: {a['simbolo']}")
            vistos.add(a["simbolo"])
            activos.append(
                Activo(
                    simbolo=a["simbolo"],
                    nombre=a["nombre"],
                    sector=a["sector"],
                    grupo=clave,
                    proveedor=g["proveedor"],
                    moneda=g["moneda"],
                    simbolo_historia=a.get("simbolo_historia"),
                )
            )
        grupos[clave] = Grupo(
            clave=clave,
            nombre=g["nombre"],
            proveedor=g["proveedor"],
            moneda=g["moneda"],
            referencia=g["referencia"],
            hora_corte=str(g["hora_corte"]),
            desfase_dias=int(g.get("desfase_dias", 0)),
            activos=tuple(activos),
        )
    return Universo(grupos=grupos, auxiliares=tuple(crudo.get("auxiliares", [])))
