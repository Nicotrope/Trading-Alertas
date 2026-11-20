# trading-alertas

Sistema de alertas de trading swing (solo largos, velas diarias). Especificación completa en
[SPEC.md](SPEC.md). **El sistema no envía órdenes a ningún bróker**: solo lee datos públicos.

Estado: **fase 2 (backtest)**. Fase 1 (datos e indicadores) terminada.

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

## Qué hay en la fase 2 (backtest)

```bash
python -m backtest.ejecutar              # ~1 minuto; necesita la caché de datos
python -m backtest.ejecutar --rapido     # sin la prueba de robustez
```

Resultado en `backtest/resultados/informe.html` (se abre sin conexión), más las operaciones en CSV.

| Pieza | Archivo | Qué hace |
| --- | --- | --- |
| Estrategias | `src/estrategias/ruptura.py`, `retroceso.py`, `regimen.py` | señales A y B, stops y filtro de régimen (las mismas que usará el sistema diario) |
| Riesgo | `src/riesgo.py` | tamaño por riesgo del 1 %, topes (20 %, cripto 20 %, mínimo 500 €), costes |
| Motor | `backtest/motor.py` | cartera completa día a día, con todos los límites de la sección 4 |
| Informe | `backtest/informe.py`, `backtest/ejecutar.py` | métricas, comparación con comprar y mantener, robustez ±20 %, HTML |
| Parámetros | `config/backtest.yaml`, `config/riesgo.yaml` | periodos, criterio de paso, costes de Trade Republic |

Decisiones del motor (revisables):

- Señal con el cierre de t, ejecución en la apertura de t+1 con deslizamiento en contra.
- Stops: si el mínimo del día toca el stop, se vende al stop; si la vela abre ya por debajo, a la apertura.
- Si A y B coinciden en un activo, es una sola posición ("A+B") gestionada con las reglas de A.
- Freno por caída: al caer un 10 % desde el máximo se pausan las compras 20 sesiones y después el máximo se
  reinicia (la especificación no dice cuándo reanudar; `freno_pausa_sesiones` en `config/riesgo.yaml`).
- Costes de Trade Republic: 1 € por operación; cripto con 0,5 % de diferencial y acciones/ETFs con 0,1 %.
- Velas antiguas incoherentes (high/low que no contienen open/close) se corrigen al cargarlas.
- Capital para el tamaño: el capital actual de la simulación (interés compuesto).

## Tests

- `tests/test_indicadores.py`: cada indicador contra valores calculados a mano (el cálculo está en los comentarios).
- `tests/test_sin_futuro.py`: para cada indicador, cortar la serie en t o cambiar todos los datos posteriores a t
  no altera ningún valor hasta t.
- `tests/test_backtest.py`: un caso calculado a mano (entrada, stop con hueco, costes) y la prueba de que cortar los
  datos en T no cambia el capital ni las operaciones hasta T. `tests/test_estrategias.py`, `tests/test_riesgo.py`: reglas y tamaños.
- `tests/test_validacion.py`, `tests/test_calendario.py`, `tests/test_cache.py`: validación con datos rotos a
  propósito, horas de corte (incluido horario de verano) y caché con un proveedor falso.

## Limitaciones conocidas

- yfinance es gratuito pero no oficial; puede fallar o cambiar. Está detrás de `DataProvider` para poder sustituirlo.
- Sesgo de supervivencia: el universo es la lista actual de empresas.
