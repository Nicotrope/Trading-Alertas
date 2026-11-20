"""Email diario: composición, contexto de IA (con cliente falso) y historial. Sin red."""
from datetime import datetime, timezone
from types import SimpleNamespace

import numpy as np
import pandas as pd

from backtest.motor import calcular_senales, cargar_mercado, simular
from src import alertas, contexto_ia
from src.main import construir_informe
from tests.test_backtest import ESTR, RIESGO, subida, universo


def _mercado(tmp_path):
    u = universo(tmp_path, ["X", "Y"])
    f = pd.date_range("2024-01-01", periods=30, freq="B")
    x = subida(30).set_index(f)                       # sube siempre: compra y después stop dinámico
    y = subida(30).set_index(f) * 0.5
    c = y["close"].iloc[-3] * 0.999                   # Y cierra bajo el mínimo de los 2 cierres previos
    y.iloc[-1] = [c, c + 0.5, c - 0.5, c]             # sin tocar el stop → venta por regla A mañana
    m = cargar_mercado(u, velas={"X": x, "Y": y, "REF": subida(30).set_index(f)}, sma_regimen=5)
    return u, m


def test_informe_compras_ventas_y_cuenta(tmp_path):
    u, m = _mercado(tmp_path)
    sen = calcular_senales(m, ESTR)
    res = simular(m, sen, ESTR, RIESGO, desde="2024-01-15", cerrar_al_final=False, usar=("A",))
    cfg = {"fecha_inicio_papel": "2024-01-15", "modo": "papel", "referencia_backtest": "ref"}
    inf = construir_informe(m, res, u, ESTR, RIESGO, cfg, datetime(2024, 2, 10).date(), ["Datos: sin incidencias."])
    assert inf.regimen == {"europa": True}
    assert [v.simbolo for v in inf.ventas] == ["Y"] and inf.ventas[0].motivo == "regla A"
    assert {p.simbolo for p in inf.posiciones} == {"X", "Y"}
    assert inf.capital == res.capital.iloc[-1]
    assert abs(inf.efectivo + sum(p.unidades * p.ultimo_eur for p in inf.posiciones) - inf.capital) < 1e-6
    t = alertas.texto(inf)
    assert "VENDER Y (Y)" in t and "MODO PAPEL" in t and "Sin incidencias" not in t.split("AVISOS")[0]
    a = alertas.asunto(inf)
    assert a.startswith("Señales 10-02-2024") and "1 venta" in a and "Europa ✔" in a
    assert "<h3" in alertas.html_email(inf)


def test_compra_lleva_unidades_stop_y_riesgo(tmp_path):
    u, m = _mercado(tmp_path)
    sen = calcular_senales(m, ESTR)
    # empezando el último día: la única acción posible es comprar en la próxima apertura
    res = simular(m, sen, ESTR, RIESGO, desde=m.fechas[-1], cerrar_al_final=False, usar=("A",))
    cfg = {"fecha_inicio_papel": str(m.fechas[-1].date()), "modo": "papel"}
    inf = construir_informe(m, res, u, ESTR, RIESGO, cfg, datetime(2024, 2, 10).date(), [])
    assert [c.simbolo for c in inf.compras] == ["X"]
    c = inf.compras[0]
    assert c.unidades > 0 and c.stop_eur < c.precio_eur
    assert abs(c.riesgo_eur - c.unidades * (c.precio_eur - c.stop_eur)) < 1e-6
    assert c.riesgo_eur <= RIESGO["capital_eur"] * RIESGO["riesgo_por_operacion"] + 1e-6
    t = alertas.texto(inf)
    assert "COMPRAR X (X)" in t and "orden stop-loss" in t


def test_historial(tmp_path):
    inf = alertas.Informe(fecha="01-02-2024", regimen={"eeuu": True})
    inf.compras.append(alertas.Compra("MSFT", "Microsoft", "eeuu", "A", 3, 400, 1200, 380, 60, False))
    ruta = tmp_path / "h.csv"
    assert alertas.guardar_historial(inf, ruta) == 1
    assert alertas.guardar_historial(inf, ruta) == 1
    h = pd.read_csv(ruta)
    assert len(h) == 2 and list(h.columns) == alertas.CAMPOS_HISTORIAL


def test_formatos():
    assert alertas.eur(1234.5) == "1.234,50 €"
    assert alertas.pct(0.062) == "+6,2%"
    assert alertas.unidades(0.025, True) == "0,025"


class ClienteFalso:
    def __init__(self, texto=None, error=None, stop="end_turn"):
        self.texto, self.error, self.stop = texto, error, stop
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))
        self.llamadas = []

    def create(self, **kw):
        self.llamadas.append(kw)
        if self.error:
            raise self.error
        return SimpleNamespace(stop_reason=self.stop, content=[SimpleNamespace(type="text", text=self.texto)])


def test_contexto_ia_parsea_y_nunca_rompe():
    pet = [contexto_ia.Peticion("MSFT", "Microsoft", "señal de compra"), contexto_ia.Peticion("BTC/EUR", "Bitcoin", "x")]
    cli = ClienteFalso("MSFT: presenta resultados el jueves.\n- BTC/EUR: sin novedades relevantes.\nOTRO: ignorar")
    ctx, aviso = contexto_ia.obtener(pet, "2024-02-10", {"modelo": "claude-opus-5-5"}, cliente=cli)
    assert ctx == {"MSFT": "presenta resultados el jueves.", "BTC/EUR": "sin novedades relevantes."} and aviso is None
    kw = cli.llamadas[0]
    assert kw["tools"][0]["type"] == "web_search_20260209" and kw["fallbacks"] == "default"
    # un fallo de la API → sin contexto, con aviso, sin excepción
    ctx, aviso = contexto_ia.obtener(pet, "2024-02-10", {}, cliente=ClienteFalso(error=RuntimeError("caída")))
    assert ctx == {} and "no disponible" in aviso
    ctx, aviso = contexto_ia.obtener(pet, "2024-02-10", {}, cliente=ClienteFalso("x", stop="refusal"))
    assert ctx == {} and aviso


def test_contexto_ia_sin_clave(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    ctx, aviso = contexto_ia.obtener([contexto_ia.Peticion("A", "A", "x")], "2024-01-01", {})
    assert ctx == {} and "falta la clave" in aviso


def test_no_envia_antes_de_hora(monkeypatch, capsys):
    from src import main

    llamado = []
    monkeypatch.setattr(main.alertas, "enviar", lambda inf: llamado.append(inf))
    # 05:00 UTC en noviembre = 06:00 en Ámsterdam → demasiado pronto
    assert main.ejecutar(ahora=datetime(2026, 11, 23, 5, 0, tzinfo=timezone.utc)) is None
    assert "Aún no" in capsys.readouterr().out and not llamado


def test_por_que_y_para_vigilar():
    from src import explicar
    p_ind = {"sma_tendencia": 200, "atr": 14, "momentum_sesiones": 126}
    p_a = {"maximo_cierres": 20, "salida_minimo": 10}
    p_b = {"rsi_periodo": 2, "rsi_entrada": 10}
    f = pd.date_range("2023-01-02", periods=300, freq="B")
    sube = pd.Series(np.linspace(100, 200, 300), index=f)
    cae = sube.copy()
    cae.iloc[-3:] = [190, 182, 175]                       # caída fuerte dentro de una subida
    baja = pd.Series(np.linspace(200, 100, 300), index=f)
    baja.iloc[-5:] = [95, 92, 90, 88, 85]                 # caída en tendencia bajista
    v = {s: pd.DataFrame({"close": c}) for s, c in {"SUBE": sube, "CAE": cae, "BAJA": baja}.items()}
    fotos = {s: explicar.foto(s, d, p_ind, p_a, p_b) for s, d in v.items()}
    t = explicar.por_que_compra(fotos["CAE"], "B")
    assert "Ha caído un" in t and "3 sesiones seguidas" in t and "por encima de su media de 200" in t
    assert "máximo de las últimas 4 semanas" in explicar.por_que_compra(fotos["SUBE"], "A")
    lista = explicar.para_vigilar(fotos, {}, {s: "eeuu" for s in v}, {"eeuu": True}, set(), p_b)
    por = {x.simbolo: x for x in lista}
    assert "BAJA" in por and "tendencia de fondo bajista" in por["BAJA"].por_que_no
    assert "CAE" in por and "por encima" in por["CAE"].por_que_no or "No es señal hoy" in por["CAE"].por_que_no
    assert "SUBE" not in por                               # en máximos: ya sería señal, no "casi"
    # lo que ya está en cartera o es compra no se repite
    assert explicar.para_vigilar(fotos, {}, {}, {}, {"BAJA", "CAE"}, p_b) == []
