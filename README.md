# Pruebas técnicas · Pharoes

Este repositorio reúne las pruebas técnicas que he resuelto en el proceso de selección para las prácticas de DAM (Desarrollo de Aplicaciones Multiplataforma). Cada prueba está en su propia carpeta, con su código, sus pruebas automáticas y un README que explica cómo ejecutarla y cómo cumple el enunciado.

| Prueba | Qué hace | Carpeta |
|---|---|---|
| 4 · Riego | Consulta la precipitación prevista para 7 días, calcula el uso estimado de riego, lo guarda en un CSV y genera un dashboard con ECharts. | [`prueba4-riego-dashboard/`](prueba4-riego-dashboard/) |
| 5 · Protección solar | Consulta el índice UV máximo previsto para 7 días, calcula el uso estimado de protección solar, lo guarda en un CSV y genera un dashboard con ECharts. | [`prueba5-proteccion-solar/`](prueba5-proteccion-solar/) |

## Cómo se ejecuta cualquiera de las dos

Requisitos: **Python 3.8 o superior** y conexión a internet. No hay que instalar ninguna librería.

```bash
cd prueba5-proteccion-solar          # o prueba4-riego-dashboard
python obtener_datos.py --ciudad Madrid
python generar_dashboard.py --ubicacion "Madrid, España"
```

Después se abre `dashboard.html` en el navegador. Para ejecutar las pruebas automáticas, desde la misma carpeta:

```bash
python -m unittest -v
```

## Enfoque común

Las dos pruebas siguen la misma estructura, porque los enunciados tienen la misma forma (datos de una API → fórmula → CSV → dashboard):

- **`obtener_datos.py`** hace los pasos 1 a 3: pide los datos a la API de [Open-Meteo](https://open-meteo.com/) (gratuita y sin clave), aplica la fórmula y guarda el CSV.
- **`plantilla_dashboard.html`** es el paso 4: el dashboard con ECharts, con dos gráficas que comparten el eje X de los días.
- **`generar_dashboard.py`** es el paso 5: lee el CSV, lo valida e inserta los datos en la plantilla. El HTML generado no se edita nunca a mano.
- **Pruebas automáticas** con `unittest`, que funcionan sin internet porque sustituyen la API por respuestas guardadas.

Las decisiones de cada prueba (qué variable de la API se usa, cómo se tratan los datos que faltan, redondeos, compatibilidad con Excel...) están explicadas en su README.

## Tecnologías

- Python 3.8+ con solo la biblioteca estándar (`urllib`, `json`, `csv`, `argparse`, `unittest`).
- HTML, CSS y JavaScript, con [Apache ECharts](https://echarts.apache.org/) 6.1.0 cargado desde jsDelivr.
- Datos meteorológicos de [Open-Meteo](https://open-meteo.com/) (licencia CC BY 4.0).
