# trading-alertas

Sistema de alertas de trading swing (solo largos, velas diarias). Especificación completa en
[SPEC.md](SPEC.md). **El sistema no envía órdenes a ningún bróker**: solo lee datos públicos.

Estado: **fase 1 (datos e indicadores)**.

## Puesta en marcha

```bash
python3.12 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
pytest                                   # tests (no necesitan red)
python -m src.datos.actualizar           # descarga, caché y validación de todo el universo
python -m src.datos.actualizar --grupos cripto --muestra BTC/EUR
```

La primera descarga trae ~12 años por activo y tarda unos minutos; las siguientes solo piden las
velas nuevas. El informe por activo queda en `datos/cache/informe_validacion.csv`.

## Qué hay en la fase 1

| Pieza | Archivo | Qué hace |
| --- | --- | --- |
| Universo | `config/universo.yaml` | ~170 activos en 4 grupos (EE. UU., Europa, ETFs UCITS, cripto) + referencias y EUR/USD |
| Parámetros de datos | `config/datos.yaml` | historia, solape, umbrales de validación |
| Interfaz de datos | `src/datos/proveedor.py` | `DataProvider` + formato común de velas |
| Yahoo | `src/datos/yahoo.py` | acciones, ETFs, índices, divisas; OHLC ajustado por dividendos y splits |
| Kraken | `src/datos/cripto.py` | velas diarias públicas vía ccxt |
| Calendario | `src/datos/calendario.py` | qué vela está cerrada a cada hora (nunca se usa una vela a medio formar) |
| Caché | `src/datos/cache.py` | Parquet por activo, incremental, redescarga si cambia el ajuste histórico |
| Validación | `src/datos/validacion.py` | huecos, precios a cero/NaN, saltos > 50 %, velas incoherentes, desfase, historia corta |
| Indicadores | `src/indicadores.py` | SMA, ATR y RSI de Wilder, máximo/mínimo de los N cierres anteriores, rentabilidad |

### Decisiones de diseño

- **Velas cerradas:** cada grupo tiene su hora de corte (Ámsterdam). Antes de esa hora, la última vela
  válida es la del día anterior; nada posterior se guarda en caché.
- **Ajustes por dividendos:** Yahoo reajusta toda la serie al pagar un dividendo. En cada actualización se
  repiten los últimos 10 días y, si los cierres cambian más de un 0,1 %, se redescarga la historia entera.
- **Cripto:** la API pública de Kraken solo devuelve unas 720 velas diarias. La historia anterior se completa
  con Yahoo (`BTC-EUR`, etc.); la columna `fuente` de la caché indica de dónde viene cada vela.
- **Validación:** los problemas en los últimos 30 días excluyen el activo (error); los antiguos se registran
  como aviso para revisarlos antes del backtest.
- **Indicadores:** implementación propia. ATR y RSI con el suavizado de Wilder. `maximo_previo(c, 20)` no
  incluye el día t, así que la ruptura es `cierre_t >= maximo_previo_t`.

## Tests

- `tests/test_indicadores.py`: cada indicador contra valores calculados a mano (el cálculo está en los comentarios).
- `tests/test_sin_futuro.py`: para cada indicador, cortar la serie en t o cambiar todos los datos posteriores a t
  no altera ningún valor hasta t.
- `tests/test_validacion.py`, `tests/test_calendario.py`, `tests/test_cache.py`: validación con datos rotos a
  propósito, horas de corte (incluido horario de verano) y caché con un proveedor falso.

## Limitaciones conocidas

- yfinance es gratuito pero no oficial; puede fallar o cambiar. Está detrás de `DataProvider` para poder sustituirlo.
- Sesgo de supervivencia: el universo es la lista actual de empresas.
