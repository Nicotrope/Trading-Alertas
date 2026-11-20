"""Email diario y historial de señales (SPEC §6).

Este módulo solo da formato y envía: las cifras vienen ya calculadas de src/main.py.
"""
from __future__ import annotations

import csv
import html
import os
import smtplib
import ssl
from dataclasses import asdict, dataclass, field
from email.message import EmailMessage
from pathlib import Path

GRUPOS = {"eeuu": "EE. UU.", "europa": "Europa", "etfs": "ETFs", "cripto": "Cripto"}
CUANDO = {
    "eeuu": "hoy a partir de las 15:30 (apertura de Wall Street)",
    "europa": "hoy a partir de las 09:00 (apertura de la bolsa)",
    "etfs": "hoy a partir de las 09:00",
    "cripto": "al recibir este email",
}
ESTRATEGIA = {
    "A": "A · ruptura: marca máximos de 20 días dentro de una tendencia alcista",
    "B": "B · retroceso: caída corta dentro de una tendencia alcista",
    "A+B": "A y B a la vez (ruptura y retroceso)",
}
MOTIVO_VENTA = {
    "regla A": "cerró por debajo del mínimo de los 10 días anteriores (fin de la tendencia)",
    "regla B": "el rebote ya se ha producido (cierre sobre la media de 5 días o RSI alto)",
    "tiempo": "lleva 10 sesiones sin salir (límite de tiempo de la estrategia B)",
    "stop": "tocó el stop de protección",
    "stop dinámico": "tocó el stop dinámico (el stop que va subiendo con el precio)",
}


@dataclass
class Compra:
    simbolo: str
    nombre: str
    grupo: str
    estrategia: str
    unidades: float
    precio_eur: float          # último cierre en EUR (referencia)
    importe_eur: float
    stop_eur: float
    riesgo_eur: float
    es_cripto: bool
    stop_nativo: float | None = None
    moneda: str = "EUR"
    resultados: str | None = None   # fecha de resultados próximos, si la hay
    contexto: str | None = None
    por_que: str | None = None      # qué ha hecho el precio, en palabras simples


@dataclass
class Venta:
    simbolo: str
    nombre: str
    grupo: str
    unidades: float
    motivo: str
    entrada_eur: float
    ultimo_eur: float
    es_cripto: bool

    @property
    def rentabilidad(self) -> float:
        return self.ultimo_eur / self.entrada_eur - 1


@dataclass
class Posicion:
    simbolo: str
    nombre: str
    grupo: str
    estrategia: str
    fecha_entrada: str
    unidades: float
    entrada_eur: float
    ultimo_eur: float
    stop_eur: float
    stop_subido: bool
    sesiones: int
    es_cripto: bool
    contexto: str | None = None
    resultados: str | None = None

    @property
    def rentabilidad(self) -> float:
        return self.ultimo_eur / self.entrada_eur - 1

    @property
    def resultado_eur(self) -> float:
        return self.unidades * (self.ultimo_eur - self.entrada_eur)


@dataclass
class Cerrada:
    simbolo: str
    nombre: str
    motivo: str
    resultado_eur: float
    rentabilidad: float


@dataclass
class Informe:
    fecha: str                       # día del email (Ámsterdam)
    regimen: dict[str, bool]
    compras: list[Compra] = field(default_factory=list)
    ventas: list[Venta] = field(default_factory=list)
    posiciones: list[Posicion] = field(default_factory=list)
    cerradas: list[Cerrada] = field(default_factory=list)
    capital: float = 0.0
    capital_inicial: float = 0.0
    fecha_inicio: str = ""
    efectivo: float = 0.0
    operaciones_cerradas: int = 0
    operaciones_ganadoras: int = 0
    avisos: list[str] = field(default_factory=list)
    referencia: str = ""
    modo: str = "papel"
    vigilar: list = field(default_factory=list)   # src.explicar.Vigilar (solo informativo)


# ---------------------------------------------------------------------------
# Formato
# ---------------------------------------------------------------------------

def eur(v: float, dec: int = 2) -> str:
    s = f"{v:,.{dec}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{s} €"


def pct(v: float) -> str:
    return f"{v:+.1%}".replace(".", ",")


def unidades(v: float, es_cripto: bool) -> str:
    if es_cripto:
        return f"{v:.6f}".rstrip("0").rstrip(",").replace(".", ",")
    return f"{int(v)}"


def asunto(inf: Informe) -> str:
    reg = " ".join(f"{GRUPOS[g]} {'✔' if v else '✘'}" for g, v in inf.regimen.items())
    nc, nv = len(inf.compras), len(inf.ventas)
    partes = [f"Señales {inf.fecha}", f"{nc} compra{'s' if nc != 1 else ''}", f"{nv} venta{'s' if nv != 1 else ''}"]
    return " · ".join(partes) + f" · régimen: {reg}"


def texto(inf: Informe) -> str:
    L: list[str] = []
    add = L.append
    if inf.modo == "papel":
        add("MODO PAPEL: es una prueba. No hace falta operar; la cuenta de abajo es simulada.\n")

    add("QUÉ HACER HOY")
    if not inf.ventas and not inf.compras:
        add("- Nada. No hay compras ni ventas hoy.")
    for v in inf.ventas:
        add(f"- VENDER {v.nombre} ({v.simbolo}): todo ({unidades(v.unidades, v.es_cripto)} uds), {CUANDO[v.grupo]}.")
        add(f"  Motivo: {MOTIVO_VENTA.get(v.motivo, v.motivo)}. Resultado aprox.: {pct(v.rentabilidad)}.")
        add("  Recuerda cancelar antes su orden stop.")
    for c in inf.compras:
        if c.es_cripto:
            add(f"- COMPRAR {c.nombre} ({c.simbolo}) por {eur(c.importe_eur, 0)}, {CUANDO[c.grupo]}.")
        else:
            add(f"- COMPRAR {c.nombre} ({c.simbolo}): {unidades(c.unidades, False)} acciones "
                f"(~{eur(c.importe_eur, 0)}), {CUANDO[c.grupo]}.")
        add(f"  Después: orden stop-loss a {eur(c.stop_eur)}"
            + (f" (= {c.stop_nativo:.2f} {c.moneda})" if c.moneda != "EUR" and c.stop_nativo else "")
            + f". Si salta, pierdes como mucho ~{eur(c.riesgo_eur, 0)}.")
        if c.por_que:
            add(f"  Por qué: {c.por_que}")
        add(f"  Regla: estrategia {ESTRATEGIA.get(c.estrategia, c.estrategia)}. Último cierre {eur(c.precio_eur)}.")
        if c.resultados:
            add(f"  ATENCIÓN: presenta resultados el {c.resultados} [resultados próximos].")
        if c.contexto:
            add(f"  Contexto: {c.contexto}")

    cambios = [p for p in inf.posiciones if p.stop_subido and p.simbolo not in {v.simbolo for v in inf.ventas}]
    if cambios:
        add("\nSUBIR STOP (posiciones que van bien)")
        for p in cambios:
            add(f"- {p.nombre} ({p.simbolo}): mueve la orden stop a {eur(p.stop_eur)}.")

    add("\nCÓMO VA LA CUENTA" + (" (simulada)" if inf.modo == "papel" else ""))
    rent = inf.capital / inf.capital_inicial - 1 if inf.capital_inicial else 0
    add(f"- Capital: {eur(inf.capital, 0)} ({pct(rent)} desde el {inf.fecha_inicio}, empezando con {eur(inf.capital_inicial, 0)}).")
    add(f"- Dinero sin invertir: {eur(inf.efectivo, 0)}. Posiciones abiertas: {len(inf.posiciones)}.")
    if inf.operaciones_cerradas:
        add(f"- Operaciones cerradas: {inf.operaciones_cerradas}, de ellas {inf.operaciones_ganadoras} con ganancia.")
    if inf.referencia:
        add(f"- {inf.referencia}")

    vender = {v.simbolo for v in inf.ventas}
    seguir = [p for p in inf.posiciones if p.simbolo not in vender]
    if seguir:
        add("\nPOSICIONES ABIERTAS (no hay que hacer nada)")
        for p in sorted(seguir, key=lambda p: -p.rentabilidad):
            add(f"- {p.nombre} ({p.simbolo}) · {pct(p.rentabilidad)} ({eur(p.resultado_eur, 0)}) · "
                f"stop {eur(p.stop_eur)} · {p.sesiones} {'sesión' if p.sesiones == 1 else 'sesiones'} · desde {p.fecha_entrada}")
            if p.resultados:
                add(f"  Presenta resultados el {p.resultados}.")
            if p.contexto:
                add(f"  Contexto: {p.contexto}")
    if inf.cerradas:
        add("\nCERRADAS EN LA ÚLTIMA SESIÓN")
        for c in inf.cerradas:
            add(f"- {c.nombre} ({c.simbolo}) · {MOTIVO_VENTA.get(c.motivo, c.motivo)} · {pct(c.rentabilidad)} ({eur(c.resultado_eur, 0)})")

    if inf.vigilar:
        add("\nPARA VIGILAR (solo información: NO son compras)")
        for v in inf.vigilar:
            add(f"- {v.nombre} ({v.simbolo}): {v.que_paso}")
            add(f"  {v.por_que_no}")

    add("\nAVISOS")
    for a in inf.avisos or ["Sin incidencias."]:
        add(f"- {a}")
    add("\nCómo operar en Trade Republic: busca el valor → Comprar → orden de mercado → número de acciones "
        "(en cripto, importe en €). Después, en el mismo valor: Vender → orden stop → precio del stop, por todas las acciones. "
        "Si la app no permite orden stop en ese activo, vigila el precio y vende si cierra por debajo.")
    add("Este email lo genera un programa con reglas fijas. No es asesoramiento financiero.")
    return "\n".join(L)


def html_email(inf: Informe) -> str:
    """Versión HTML sencilla (estilos en línea para que se vea bien en Gmail)."""
    cuerpo = []
    for linea in texto(inf).split("\n"):
        e = html.escape(linea)
        cab = linea.split(" (")[0]
        if cab and cab == cab.upper() and not linea.startswith(("-", " ")):
            cuerpo.append(f"<h3 style='margin:18px 0 6px;font-size:15px;color:#1b3a6b'>{e}</h3>")
        elif linea.startswith("- COMPRAR"):
            cuerpo.append(f"<p style='margin:8px 0 2px;color:#1a7f37;font-weight:600'>{e[2:]}</p>")
        elif linea.startswith("- VENDER"):
            cuerpo.append(f"<p style='margin:8px 0 2px;color:#c62828;font-weight:600'>{e[2:]}</p>")
        elif linea.startswith("  "):
            cuerpo.append(f"<p style='margin:0 0 0 16px;color:#444'>{e.strip()}</p>")
        elif linea.startswith("- "):
            cuerpo.append(f"<p style='margin:2px 0'>• {e[2:]}</p>")
        elif linea.strip():
            cuerpo.append(f"<p style='margin:6px 0;color:#555'>{e}</p>")
    return ("<div style='font-family:Arial,Helvetica,sans-serif;font-size:14px;line-height:1.45;max-width:640px'>"
            + "".join(cuerpo) + "</div>")


# ---------------------------------------------------------------------------
# Envío e historial
# ---------------------------------------------------------------------------

def enviar(inf: Informe) -> None:
    """SMTP con las variables de entorno SMTP_USUARIO, SMTP_CLAVE, EMAIL_DESTINO
    (y opcionales SMTP_SERVIDOR, SMTP_PUERTO; por defecto Gmail)."""
    usuario = os.environ["SMTP_USUARIO"]
    clave = os.environ["SMTP_CLAVE"]
    destino = os.environ.get("EMAIL_DESTINO") or usuario
    msg = EmailMessage()
    msg["Subject"] = asunto(inf)
    msg["From"] = usuario
    msg["To"] = destino
    msg.set_content(texto(inf))
    msg.add_alternative(html_email(inf), subtype="html")
    servidor = os.environ.get("SMTP_SERVIDOR", "smtp.gmail.com")
    puerto = int(os.environ.get("SMTP_PUERTO", "465"))
    with smtplib.SMTP_SSL(servidor, puerto, context=ssl.create_default_context(), timeout=60) as s:
        s.login(usuario, clave)
        s.send_message(msg)


CAMPOS_HISTORIAL = ["fecha", "tipo", "activo", "nombre", "estrategia", "unidades", "precio_ref_eur",
                    "importe_eur", "stop_eur", "motivo", "resultados_proximos"]


def guardar_historial(inf: Informe, ruta: Path) -> int:
    filas = []
    for c in inf.compras:
        filas.append({"fecha": inf.fecha, "tipo": "compra", "activo": c.simbolo, "nombre": c.nombre,
                      "estrategia": c.estrategia, "unidades": c.unidades, "precio_ref_eur": round(c.precio_eur, 4),
                      "importe_eur": round(c.importe_eur, 2), "stop_eur": round(c.stop_eur, 4), "motivo": "",
                      "resultados_proximos": c.resultados or ""})
    for v in inf.ventas:
        filas.append({"fecha": inf.fecha, "tipo": "venta", "activo": v.simbolo, "nombre": v.nombre, "estrategia": "",
                      "unidades": v.unidades, "precio_ref_eur": round(v.ultimo_eur, 4), "importe_eur": "",
                      "stop_eur": "", "motivo": v.motivo, "resultados_proximos": ""})
    for p in inf.posiciones:
        if p.stop_subido:
            filas.append({"fecha": inf.fecha, "tipo": "subir_stop", "activo": p.simbolo, "nombre": p.nombre,
                          "estrategia": p.estrategia, "unidades": p.unidades, "precio_ref_eur": round(p.ultimo_eur, 4),
                          "importe_eur": "", "stop_eur": round(p.stop_eur, 4), "motivo": "", "resultados_proximos": ""})
    if not filas:
        return 0
    ruta.parent.mkdir(parents=True, exist_ok=True)
    nuevo = not ruta.exists() or ruta.stat().st_size == 0
    with open(ruta, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CAMPOS_HISTORIAL)
        if nuevo:
            w.writeheader()
        w.writerows(filas)
    return len(filas)


def a_dict(inf: Informe) -> dict:
    return asdict(inf)
