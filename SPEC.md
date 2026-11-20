# Especificación: sistema de alertas de trading swing

Nov 20, 2026 · @Nico

## 1. Objetivo y alcance

Un sistema que cada día analiza una lista fija de activos, detecta señales de compra y venta de tipo swing (operaciones de días a semanas) y envía un email con lo que hay que hacer. El sistema **no ejecuta órdenes**: Nico decide y opera manualmente en su bróker.

- **Mercados:** acciones de EE. UU., acciones europeas, ETFs y cripto.
- **Dirección:** solo largos (compras) en la versión 1. Nada de cortos ni derivados.
- **Frecuencia:** datos diarios (velas de 1 día). Sin intradía.
- **Salida:** un email diario y un registro histórico de señales en CSV.
- **Fuera de alcance en v1:** ejecución automática, conexión a bróker, apalancamiento, opciones, cortos.

Principio de diseño: las señales las genera código determinista y reproducible. El LLM solo añade contexto (noticias, resultados próximos) y nunca crea ni anula una señal.

Este documento es una especificación técnica, no asesoramiento financiero.

## 2. Universo de activos y datos

La v1 trabaja con unos 180 activos líquidos, definidos en un archivo de configuración editable (`config/universo.yaml`). Ampliar la lista no requiere tocar código.

| Grupo | Composición inicial | Índice de referencia (filtro de régimen) | Fuente de datos v1 | Hora de corte (Ámsterdam) |
| --- | --- | --- | --- | --- |
| Acciones EE. UU. | Componentes del S&P 100 | S&P 500 (SPY) | yfinance | 22:30 |
| Acciones Europa | Euro Stoxx 50 + AEX 25 | Euro Stoxx 50 | yfinance | 18:00 |
| ETFs | ~15: índices amplios, sectores, bonos, oro | Su propio índice o SPY | yfinance | 22:30 |
| Cripto | BTC, ETH y 5–8 grandes por capitalización | BTC | ccxt (exchange público) | 01:30 (cierre diario 00:00 UTC) |

Requisitos de datos:

- Velas diarias OHLCV ajustadas por dividendos y splits, con al menos 10 años de historia (o toda la disponible en cripto).
- Caché local en Parquet para no descargar todo cada día; solo se piden las velas nuevas.
- Validación tras cada descarga: huecos, precios a cero, saltos de más del 50% en un día. Un activo con datos dudosos se excluye ese día y se avisa en el email.
- La capa de datos va detrás de una interfaz (`DataProvider`) para poder cambiar yfinance por una fuente de pago sin tocar el resto.

Nota: yfinance es gratuito pero no oficial y a veces falla; sirve para prototipo y backtest. Si el sistema pasa a uso real, conviene evaluar una fuente de pago.

## 3. Reglas de señales

Dos estrategias complementarias de solo compra, más un filtro de régimen común. Todas las reglas se evalúan con el cierre del día t y la entrada sugerida es la apertura del día t+1. Los valores son puntos de partida estándar; el backtest decide los definitivos y todos viven en `config/estrategias.yaml`.

| Elemento | A. Ruptura en tendencia | B. Retroceso en tendencia |
| --- | --- | --- |
| Idea | Comprar fuerza que marca máximos | Comprar una caída corta dentro de una subida |
| Tendencia | Cierre > media simple de 200 días | Cierre > media simple de 200 días |
| Disparador | Cierre ≥ máximo de los 20 cierres anteriores | RSI(2) < 10 |
| Stop inicial | Entrada − 2 × ATR(14) | Entrada − 2 × ATR(14) |
| Salida por regla | Cierre < mínimo de los 10 días anteriores | Cierre > media de 5 días, o RSI(2) > 70 |
| Stop dinámico | Máximo cierre desde la entrada − 3 × ATR(14); solo sube | No |
| Salida por tiempo | No | 10 sesiones sin salir |
| Duración típica esperada | Semanas | Días |

Filtro de régimen: no se abren compras en un grupo si su índice de referencia (sección 2) cierra por debajo de su media de 200 días. Las posiciones abiertas se siguen gestionando con sus reglas de salida.

Otras reglas:

- La salida que llegue primero gana (stop, regla o tiempo).
- Si un activo da señal por A y B a la vez, cuenta como una sola señal (se registra que coincidieron).
- No se repite señal en un activo con posición abierta.
- Si hay más señales que huecos libres (sección 4), se priorizan por rentabilidad de los últimos 6 meses (momentum relativo), de mayor a menor.
- Acciones con resultados trimestrales en los próximos 3 días hábiles: la señal se emite pero marcada "resultados próximos".

## 4. Gestión de riesgo y tamaño de posición

Cada señal llega con el número de unidades ya calculado, de forma que tocar el stop cueste como máximo el 1% de la cuenta. Así un activo volátil (cripto) recibe automáticamente una posición más pequeña que uno tranquilo (un ETF de bonos).

```
unidades = (capital × riesgo por operación) / (entrada − stop)
```

Límites (valores iniciales, todos en `config/riesgo.yaml`; los decide Nico):

| Parámetro | Valor inicial |
| --- | --- |
| Capital de referencia | A definir por Nico (en EUR) |
| Riesgo por operación | 1% del capital |
| Posiciones abiertas máximas | 8 |
| Tamaño máximo de una posición | 20% del capital |
| Exposición máxima a cripto | 20% del capital |
| Posiciones máximas en el mismo sector | 2 |
| Tamaño mínimo de una posición | 500 EUR (por debajo, las comisiones pesan demasiado) |
| Freno por caída | Caída de 10% desde el máximo de la cuenta → se pausan las señales de compra y se avisa |

Detalles de cálculo:

- Todo se calcula en EUR; los activos en USD se convierten con el tipo EUR/USD del día.
- Acciones y ETFs se redondean a unidades enteras hacia abajo; cripto admite decimales.
- Si los límites impiden una señal, se informa en el email con el motivo ("sin hueco", "límite cripto", "límite sector").
- El capital y las posiciones abiertas se leen de `datos/cartera.csv`, que mantiene Nico (sección 6).

## 5. Backtesting

El backtest usa exactamente el mismo código de señales y riesgo que el sistema diario, para que lo probado sea lo que luego se usa. Ninguna estrategia pasa a alertas reales sin superar la validación fuera de muestra.

Metodología:

- **Periodo:** 2014–2023 para optimizar (dentro de muestra) y de 2024 a hoy reservado solo para validar (fuera de muestra). Cripto, desde que haya datos.
- **Sin mirar al futuro:** la señal usa el cierre de t y se ejecuta a la apertura de t+1. Ningún indicador puede usar datos posteriores a t.
- **Costes:** comisión configurable por mercado (inicial: 3 EUR por operación en acciones y ETFs, 0,2% en cripto) más un deslizamiento de 0,1% en acciones y ETFs y 0,3% en cripto.
- **Simulación de cartera completa:** se respetan todos los límites de la sección 4, no solo operaciones sueltas.
- **Sesgo de supervivencia:** la v1 usa la composición actual de los índices, lo que infla resultados. Se documenta como limitación conocida.
- **Robustez:** variar cada parámetro ±20% (por ejemplo, ruptura de 15, 20 y 25 días). Si el resultado se hunde con cambios pequeños, la estrategia está sobreajustada.

Informe por estrategia, por grupo de activos y total:

- Rentabilidad anual compuesta, máxima caída desde máximo, ratio de Sharpe.
- Número de operaciones, porcentaje de aciertos, ganancia media / pérdida media, duración media.
- Comparación con simplemente comprar y mantener el índice de referencia.
- Gráfico de evolución del capital y de las caídas, guardado en HTML.

Criterio para pasar a la fase de alertas: fuera de muestra, la máxima caída no supera el 20% y la estrategia no queda claramente peor que comprar y mantener con su riesgo ajustado (Sharpe). Nico puede endurecer estos umbrales.

## 6. Alertas diarias

Un único email cada día a las 07:00 (Ámsterdam), con los cierres del día anterior de Europa y EE. UU. y el cierre diario de cripto. Así las señales llegan antes de la apertura europea (09:00) y estadounidense (15:30).

Estructura del email:

```
Asunto: Señales 2026-11-21 · 2 compras · 1 venta · régimen: EE. UU. ✔ Europa ✔ Cripto ✘

VENTAS / SALIDAS (posiciones abiertas)
- ASML · regla A · cierre bajo mínimo de 10 días → vender a la apertura

COMPRAS NUEVAS
- MSFT · regla A (ruptura 20 días) · entrada ~ apertura · stop 402,10 USD · 9 uds · riesgo 98 EUR
  Contexto: resultados en 2 días hábiles. [resultados próximos]
- IWDA · regla B (retroceso) · entrada ~ apertura · stop 92,40 EUR · 21 uds · riesgo 100 EUR

POSICIONES ABIERTAS
- NVDA · +6,2% · stop dinámico subido a 131,50 USD · 8 días

AVISOS
- Cripto en régimen bajista: sin compras nuevas en cripto.
- 1 señal descartada: SAP (límite sector).
- Datos: sin incidencias.
```

Cartera: Nico mantiene `datos/cartera.csv` con lo que realmente compra y vende, con las columnas `activo, estrategia, fecha_entrada, precio_entrada, unidades, stop_inicial`, y `config/riesgo.yaml` con el capital. El sistema nunca asume que una señal se ejecutó: solo gestiona las posiciones que aparecen en ese archivo.

Capa de contexto (IA):

- Para cada señal nueva y cada posición abierta, una llamada a la API de Claude con búsqueda web resume en una o dos frases lo relevante: resultados próximos, noticias importantes, movimientos anómalos.
- La IA solo añade texto de contexto. No puede crear, cancelar ni modificar señales, stops ni tamaños.
- Si la API falla, el email sale igual, sin contexto, con un aviso.

Envío: SMTP (por ejemplo, Gmail con contraseña de aplicación). Además, cada señal se guarda en `datos/historial_senales.csv` para revisar después qué se emitió y qué pasó.

## 7. Arquitectura técnica

Un proyecto Python en un repositorio privado de GitHub, ejecutado cada mañana por GitHub Actions, sin servidores propios. Cada paso es un módulo separado y probado.

Flujo diario:

1. Cargar configuración (universo, estrategias, riesgo) y cartera.
2. Actualizar datos y validar (sección 2).
3. Calcular indicadores y filtro de régimen.
4. Evaluar salidas de posiciones abiertas y actualizar stops dinámicos.
5. Evaluar señales de compra, priorizar y aplicar límites de riesgo.
6. Añadir contexto con la API de Claude.
7. Componer y enviar el email; guardar historial.

Estructura de archivos:

```
trading-alertas/
├── config/
│   ├── universo.yaml        # activos por grupo
│   ├── estrategias.yaml     # parámetros de A y B
│   └── riesgo.yaml          # capital y límites
├── datos/
│   ├── cartera.csv          # posiciones reales (las edita Nico)
│   └── historial_senales.csv
├── src/
│   ├── datos/               # DataProvider, yfinance, ccxt, validación, caché
│   ├── indicadores.py       # SMA, ATR, RSI, máximos/mínimos (implementación propia)
│   ├── estrategias/         # ruptura.py, retroceso.py, regimen.py
│   ├── riesgo.py            # tamaño y límites
│   ├── contexto_ia.py       # llamada a Claude, con fallback
│   ├── alertas.py           # email y historial
│   └── main.py              # flujo diario
├── backtest/
│   ├── motor.py             # simulación de cartera
│   └── informe.py           # métricas y gráficos HTML
├── tests/
└── .github/workflows/diario.yml
```

Tecnología: Python 3.12, pandas, pyarrow, yfinance, ccxt, PyYAML, el SDK de Anthropic, plotly para los informes y pytest. Los indicadores se implementan a mano (son pocas líneas) para no depender de librerías poco mantenidas.

Configuración y secretos:

- Claves (API de Anthropic, contraseña SMTP, email destino) en GitHub Secrets, nunca en el código.
- Modelo de IA configurable; uno rápido y barato basta para resumir noticias.
- Cron de GitHub Actions en UTC: hay que ajustarlo para que caiga a las 07:00 de Ámsterdam tanto en horario de invierno como de verano.
- Caché de datos con la caché de GitHub Actions; si se pierde, se reconstruye descargando de nuevo.
- Se puede ejecutar también en local con `python -m src.main --dry-run` (no envía email, imprime el resultado).

## 8. Fases y criterios de aceptación

Se construye por fases y no se avanza a la siguiente hasta cumplir los criterios de la anterior.

| Fase | Entregable | Criterio para avanzar | Duración orientativa |
| --- | --- | --- | --- |
| 1. Datos e indicadores | Descarga, caché, validación e indicadores con tests | Tests de indicadores contra valores calculados a mano; datos de los ~180 activos sin errores | 1 semana |
| 2. Backtest | Motor de cartera e informe HTML por estrategia y grupo | Criterios de la sección 5 cumplidos fuera de muestra | 2–3 semanas |
| 3. Alertas en papel | Email diario automático; Nico anota las señales sin operar | 1–2 meses de emails sin fallos; resultados en vivo coherentes con el backtest | 1–2 meses |
| 4. Operar con poco | Nico ejecuta las señales con un capital pequeño | Revisión mensual: seguir, ajustar o parar | Continua |

Decisiones pendientes de Nico antes de la fase 2:

- [x] Capital de referencia en EUR
- [x] Bróker y sus comisiones reales (para ajustar los costes del backtest)
- [x] Lista final de ETFs y criptos
- [x] Email de destino de las alertas

Instrucciones para Claude Code (pegar al iniciar el proyecto, junto con este documento guardado como `SPEC.md`):

```
Lee SPEC.md: es la especificación completa de un sistema de alertas de trading swing.
Construye solo la fase 1 por ahora. Reglas de trabajo:
- Sigue la estructura de archivos de la sección 7.
- Todos los parámetros van en los YAML de config/, nunca fijos en el código.
- Ningún cálculo puede usar datos posteriores al día evaluado; añade tests que lo comprueben.
- Escribe tests con pytest para cada indicador y cada regla.
- El sistema nunca envía órdenes a ningún bróker.
- Antes de empezar, dime qué vas a construir y pregúntame lo que no esté claro.
Al terminar, enséñame los resultados de los tests y una muestra de datos validados.
```
