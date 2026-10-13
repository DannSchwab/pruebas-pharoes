# Prueba 5 · Protección solar y dashboard

Obtiene el índice UV máximo previsto para los próximos 7 días en una localidad, calcula el uso estimado de protección solar de cada día, lo guarda en un CSV y, a partir de ese CSV, genera un dashboard web con ECharts.

## Cómo se ejecuta

Requisitos: **Python 3.8 o superior** y conexión a internet. No hay que instalar ninguna librería.

```bash
python obtener_datos.py --ciudad Madrid                   # pasos 1-3 -> proteccion_solar.csv
python generar_dashboard.py --ubicacion "Madrid, España"  # pasos 4-5 -> dashboard.html
```

Después basta con abrir `dashboard.html` en el navegador. En Windows, si `python` no funciona, prueba con `py`.

Si `proteccion_solar.csv` cambia, se vuelve a ejecutar `python generar_dashboard.py` y el dashboard se actualiza. El HTML no se edita nunca a mano.

### Opciones

| Script | Opción | Para qué sirve |
|---|---|---|
| `obtener_datos.py` | `--ciudad NOMBRE` | Localidad que se consulta (por defecto, Madrid). |
| | `--pais CÓDIGO` | Elige el país cuando hay localidades con el mismo nombre (`ES`, `CO`, `MX`...). |
| | `--lat GRADOS --lon GRADOS` | Coordenadas en lugar del nombre. |
| | `--dias N` | Días de previsión, de 1 a 16 (por defecto, 7). |
| | `--salida RUTA` | CSV que se genera (por defecto, `proteccion_solar.csv`). |
| `generar_dashboard.py` | `--csv RUTA` | CSV que se lee (por defecto, `proteccion_solar.csv`). |
| | `--salida RUTA` | HTML que se genera (por defecto, `dashboard.html`). |
| | `--ubicacion TEXTO` | Localidad que aparece en la cabecera del dashboard. |

## Ficheros

```
obtener_datos.py          Pasos 1-3: API de Open-Meteo -> fórmula -> proteccion_solar.csv
generar_dashboard.py      Paso 5: lee el CSV y genera dashboard.html con la plantilla
plantilla_dashboard.html  Paso 4: el dashboard (HTML, CSS y ECharts), sin datos
test_proteccion_solar.py  Pruebas automáticas
```

Al ejecutar los dos scripts se crean `proteccion_solar.csv` y `dashboard.html`.

## Cómo se cumple cada punto del enunciado

| Punto | Dónde | Cómo |
|---|---|---|
| 1. Índice UV de 7 días | `obtener_indice_uv()` | API de Open-Meteo, variable `uv_index_max` (índice UV máximo de cada día), `forecast_days=7`, con los días en la hora local de la localidad. El nombre de la ciudad se convierte en coordenadas con su API de geocodificación. |
| 2. Uso estimado | `calcular_uso_proteccion()` | `(UV - 3) x 5` si UV >= 3; `0` si UV < 3. |
| 3. CSV | `guardar_csv()` | Columnas `Día`, `Índice UV máximo` y `Uso estimado de protección solar`. |
| 4. Dashboard con ECharts | `plantilla_dashboard.html` | Arriba, el índice UV (barras); abajo, el uso estimado (línea). Las dos usan los mismos días en el eje X y tienen título y nombre en ambos ejes. |
| 5. Generación automática | `generar_dashboard.py` | Lee el CSV, lo valida y sustituye un marcador de la plantilla por los datos en formato JSON. |

## Decisiones técnicas

- **Open-Meteo** porque es gratuita, no necesita clave de API (para uso no comercial) y tiene geocodificación, así que se puede ejecutar sin registrarse. Su licencia (CC BY 4.0) pide citar la fuente, y por eso aparece en el pie del dashboard.
- **`uv_index_max` y no `uv_index_clear_sky_max`.** La primera tiene en cuenta las nubes previstas; la segunda supone cielo despejado, así que exageraría el uso en los días nublados. Los 7 días empiezan hoy, como en cualquier previsión.
- **Solo biblioteca estándar** (`urllib`, `json`, `csv`, `argparse`): no hay nada que instalar.
- **Plantilla y datos separados.** La plantilla no contiene datos: el generador inserta un objeto JSON con los días y los valores. Así el HTML siempre sale del CSV. Al insertarlo se escapan `<`, `>` y `&`, de modo que ningún texto (por ejemplo, `</script>` en `--ubicacion`) puede romper la página.
- **Un único sitio para el formato.** Las columnas del CSV, el umbral (3) y el factor (5) están definidos en `obtener_datos.py`, y el generador los importa de ahí.
- **El umbral de la fórmula coincide con el de la OMS.** La OMS recomienda protegerse del sol a partir de un índice UV de 3, que es donde empieza el nivel moderado. Por eso la gráfica del UV colorea cada barra según los niveles de la OMS (bajo, moderado, alto, muy alto y extremo, los mismos que usa AEMET) y marca el umbral con una línea discontinua: así se ve qué días generan uso.
- **Eje X compartido de verdad.** Las dos gráficas usan la misma lista de días y los mismos márgenes, así que cada día queda alineado verticalmente (comprobado en el navegador, también en el móvil). Además, `echarts.connect()` sincroniza el tooltip: al pasar el ratón por un día se ve su valor en las dos gráficas.
- **Escalas.** La del UV va de 0 a 12 aunque los valores sean bajos (si algún día lo supera, se amplía): así se ve cada día frente a los niveles de riesgo y se pueden comparar semanas distintas. El uso no tiene un máximo natural, así que su escala se ajusta a los datos (como mínimo, de 0 a 10).
- **Redondeo.** En coma flotante, `(4.35 - 3) * 5` da `6.749999999999998`, así que el resultado se redondea a 2 decimales.
- **Un dato que falta no se convierte en 0.** Si la API no devuelve el índice UV de algún día, el script se detiene con un mensaje claro en vez de inventar un valor que falsearía el uso.
- **Unidades del uso.** El enunciado no las indica, así que se muestra sin unidad, como un valor relativo.
- **CSV pensado también para Excel.** Se guarda en UTF-8 con BOM para que Excel muestre bien las tildes. El generador acepta además el CSV tal como lo guarda Excel en español: separador `;`, coma decimal, fechas `dd/mm/aaaa` y codificación Windows-1252. Si alguien edita el CSV y el uso no cuadra con la fórmula, el generador avisa, pero muestra el valor del CSV.
- **ECharts 6.1.0 desde el CDN de jsDelivr**, con hash de integridad (SRI) para que el navegador rechace el fichero si alguien lo modifica. Sin internet, la página lo avisa y el resumen y la tabla de datos siguen funcionando.
- **Presentación.** Modo claro y oscuro según el sistema, diseño adaptado al móvil, números en formato español, un resumen del periodo y una tabla con todos los valores (útil también para lectores de pantalla). Los colores de los niveles están comprobados para que se distingan también con daltonismo, y cada barra lleva su valor escrito, así que el color nunca es la única pista.

## Pruebas

```bash
python -m unittest -v
```

Son 24 pruebas y no necesitan internet, porque la API se sustituye por respuestas guardadas: la de geocodificación es una respuesta real (recortada), y la de previsión tiene el formato exacto de la API con valores de ejemplo. Cubren la fórmula (incluidos los casos límite de 2,99, 3 y 3,01), la lectura de la respuesta de la API, que un dato que falta no se convierta en 0, los errores de la API, el formato del CSV, los CSV guardados desde Excel, los errores en el CSV, la regeneración del HTML al cambiar el CSV y que un texto no pueda romper la página. Pasan con Python 3.8, 3.11, 3.12 y 3.13.

## Problemas frecuentes

- **`CERTIFICATE_VERIFY_FAILED` en macOS:** ejecuta una vez `Install Certificates.command`, que está en la carpeta de Python dentro de Aplicaciones.
- **No se puede guardar el CSV en Windows:** probablemente está abierto en Excel; ciérralo y vuelve a ejecutar el script.
- **Excel muestra todo en una columna:** en español, Excel espera `;` como separador. Importa el CSV desde la pestaña *Datos* (opción *Desde texto/CSV*) y elige la coma como delimitador.
- **No aparecen las gráficas:** el dashboard carga ECharts desde internet; comprueba la conexión y recarga la página.
