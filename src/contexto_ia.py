"""Contexto de noticias con la API de Claude (SPEC §6).

La IA solo añade texto: nunca crea, cancela ni modifica señales, stops ni tamaños.
Si no hay clave o la llamada falla, se devuelve {} y el email sale sin contexto.
Se hace UNA sola llamada para todos los activos del día (más barato).
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass

FALLBACK_BETA = "server-side-fallback-2026-07-01"


@dataclass
class Peticion:
    simbolo: str
    nombre: str
    situacion: str      # p. ej. "señal de compra" o "posición abierta, +6 %"


SISTEMA = (
    "Eres un asistente que resume noticias para un inversor particular que opera swing trading. "
    "Para cada activo de la lista busca en la web lo relevante de los últimos días: resultados "
    "trimestrales próximos o recientes, noticias importantes, movimientos anómalos del precio. "
    "Responde en español, en una o dos frases por activo, sin recomendar comprar ni vender. "
    "Devuelve exactamente una línea por activo con el formato `SIMBOLO: texto`, usando el símbolo "
    "tal como aparece en la lista. Si no hay nada relevante, escribe `SIMBOLO: sin novedades relevantes.`"
)


def _prompt(peticiones: list[Peticion], fecha: str) -> str:
    lineas = [f"- {p.simbolo} ({p.nombre}): {p.situacion}" for p in peticiones]
    return f"Fecha de hoy: {fecha}.\nActivos:\n" + "\n".join(lineas)


def parsear(texto: str, simbolos: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    validos = {s.upper(): s for s in simbolos}
    for linea in texto.splitlines():
        m = re.match(r"^\s*[-*•]?\s*`?([A-Za-z0-9.^/=_-]+)`?\s*:\s*(.+)$", linea)
        if m and m.group(1).upper() in validos:
            out[validos[m.group(1).upper()]] = m.group(2).strip()
    return out


def obtener(peticiones: list[Peticion], fecha: str, cfg: dict, cliente=None) -> tuple[dict[str, str], str | None]:
    """Devuelve (contexto por símbolo, aviso). El aviso explica por qué no hay contexto."""
    if not peticiones:
        return {}, None
    if not cfg.get("activo", True):
        return {}, None
    if cliente is None:
        if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
            return {}, "Contexto de noticias desactivado (falta la clave de la API de Claude)."
        try:
            import anthropic
        except ImportError:
            return {}, "Contexto de noticias no disponible (falta el paquete anthropic)."
        cliente = anthropic.Anthropic()
    try:
        mensajes = [{"role": "user", "content": _prompt(peticiones, fecha)}]
        texto = ""
        for _ in range(3):   # pause_turn: la búsqueda web puede pedir continuar
            r = cliente.beta.messages.create(
                model=cfg.get("modelo", "claude-opus-5-5"),
                max_tokens=16000,
                system=SISTEMA,
                messages=mensajes,
                tools=[{"type": "web_search_20260209", "name": "web_search", "max_uses": int(cfg.get("max_busquedas", 5))}],
                output_config={"effort": cfg.get("esfuerzo", "low")},
                betas=[FALLBACK_BETA],
                fallbacks="default",
            )
            texto += "".join(b.text for b in r.content if getattr(b, "type", None) == "text")
            if r.stop_reason == "pause_turn":
                mensajes = mensajes + [{"role": "assistant", "content": r.content}]
                continue
            if r.stop_reason == "refusal":
                return {}, "Contexto de noticias no disponible hoy (la IA no respondió)."
            break
        ctx = parsear(texto, [p.simbolo for p in peticiones])
        return ctx, None if ctx else "Contexto de noticias no disponible hoy (respuesta vacía)."
    except Exception as e:  # nunca se para el email por la IA
        return {}, f"Contexto de noticias no disponible hoy ({type(e).__name__})."
