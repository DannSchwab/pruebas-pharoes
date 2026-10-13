#!/usr/bin/env python3
"""Prueba 5 - Paso 5: genera el dashboard HTML a partir del CSV.

Lee el CSV, comprueba los datos y los inserta en formato JSON en la plantilla
plantilla_dashboard.html (paso 4), que tiene el HTML, el CSS y las gráficas de
ECharts. El HTML generado no se edita nunca a mano: si el CSV cambia, se vuelve
a ejecutar este script.

Ejemplos:
    python generar_dashboard.py --ubicacion "Madrid, España"
    python generar_dashboard.py --csv otro.csv --salida otro.html

Solo usa la biblioteca estándar de Python (3.8 o superior).
"""

import argparse
import csv
import io
import json
import math
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from obtener_datos import (COL_DIA, COL_USO, COL_UV, COLUMNAS, CSV_POR_DEFECTO, FACTOR, UMBRAL_UV,
                           calcular_uso_proteccion, formatear_numero)

PLANTILLA = Path(__file__).resolve().parent / "plantilla_dashboard.html"
MARCADOR = "__DATOS_DASHBOARD__"           # aparece una sola vez en la plantilla
FORMATOS_FECHA = ("%Y-%m-%d", "%d/%m/%Y")  # el del script y el de Excel en español
HTML_POR_DEFECTO = "dashboard.html"


class ErrorDashboard(Exception):
    """Problema en el CSV o en la plantilla, con un mensaje pensado para el usuario."""


# ---------------------------------------------------------------------------
# Lectura y validación del CSV
# ---------------------------------------------------------------------------
def leer_texto(ruta: Path) -> str:
    """Lee el CSV en UTF-8 (con o sin BOM) o, si no lo es, en Windows-1252 (Excel en español)."""
    contenido = ruta.read_bytes()
    try:
        return contenido.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            return contenido.decode("cp1252")
        except UnicodeDecodeError:
            raise ErrorDashboard("No se reconoce la codificación del CSV. Guárdalo en UTF-8.") from None


def leer_numero(texto: str, columna: str, linea: int) -> float:
    """Convierte un valor del CSV en número. Acepta punto o coma decimal (4.35 o 4,35)."""
    limpio = texto.strip()
    if not limpio:
        raise ErrorDashboard(f'Línea {linea}: falta el valor de "{columna}".')
    if "," in limpio:  # formato español: 1.234,5 -> 1234.5
        limpio = limpio.replace(".", "").replace(",", ".")
    try:
        valor = float(limpio)
    except ValueError:
        raise ErrorDashboard(f'Línea {linea}: "{texto.strip()}" no es un número válido en "{columna}".') from None
    if not math.isfinite(valor) or valor < 0:
        raise ErrorDashboard(f'Línea {linea}: "{columna}" tiene que ser un número de 0 en adelante (hay "{texto.strip()}").')
    return valor


def leer_fecha(texto: str, linea: int) -> date:
    """Acepta aaaa-mm-dd (lo que escribe obtener_datos.py) y dd/mm/aaaa (Excel en español)."""
    for formato in FORMATOS_FECHA:
        try:
            return datetime.strptime(texto.strip(), formato).date()
        except ValueError:
            pass
    raise ErrorDashboard(f'Línea {linea}: la fecha "{texto.strip()}" no es válida (formato aaaa-mm-dd o dd/mm/aaaa).')


def leer_csv(ruta) -> Tuple[List[dict], List[str]]:
    """Lee y valida el CSV.

    Devuelve las filas ordenadas por día ({"dia", "uv", "uso"}) y una lista de avisos.
    Detecta solo el separador: coma (lo que escribe obtener_datos.py) o punto y coma
    (lo que escribe Excel en español).
    """
    ruta = Path(ruta)
    if not ruta.is_file():
        raise ErrorDashboard(f"No existe el fichero {ruta}. Genéralo primero con: python obtener_datos.py")
    texto = leer_texto(ruta)

    registros = list(csv.reader(io.StringIO(texto), delimiter=_separador(texto)))
    # Se numeran como en el fichero (la cabecera es la línea 1) y se quitan las líneas vacías.
    lineas = [(n, valores) for n, valores in enumerate(registros, start=1) if any(v.strip() for v in valores)]
    if not lineas:
        raise ErrorDashboard("El CSV está vacío.")

    cabecera = [nombre.strip() for nombre in lineas[0][1]]
    faltan = [columna for columna in COLUMNAS if columna not in cabecera]
    if faltan:
        raise ErrorDashboard(
            "Faltan columnas: " + ", ".join(f'"{c}"' for c in faltan)
            + ". El CSV tiene que tener las columnas " + ", ".join(f'"{c}"' for c in COLUMNAS) + "."
        )
    posicion = {columna: cabecera.index(columna) for columna in COLUMNAS}

    filas, avisos, dias_vistos = [], [], {}
    for linea, valores in lineas[1:]:
        valores = valores + [""] * (len(cabecera) - len(valores))  # celdas finales vacías
        dia = leer_fecha(valores[posicion[COL_DIA]], linea)
        uv = leer_numero(valores[posicion[COL_UV]], COL_UV, linea)
        uso = leer_numero(valores[posicion[COL_USO]], COL_USO, linea)

        if dia in dias_vistos:
            raise ErrorDashboard(f"Línea {linea}: el día {dia:%d/%m/%Y} está repetido (ya aparece en la línea {dias_vistos[dia]}).")
        dias_vistos[dia] = linea

        esperado = calcular_uso_proteccion(uv)
        if abs(esperado - uso) > 0.015:
            avisos.append(
                f"línea {linea}: el uso estimado ({formatear_numero(uso)}) no coincide con la fórmula "
                f"para un índice UV de {formatear_numero(uv)} ({formatear_numero(esperado)}). Se muestra el valor del CSV."
            )
        filas.append({"dia": dia, "uv": uv, "uso": uso})

    if not filas:
        raise ErrorDashboard("El CSV no tiene filas de datos, solo la cabecera.")
    filas.sort(key=lambda fila: fila["dia"])
    return filas, avisos


def _separador(texto: str) -> str:
    primera_linea = next((l for l in texto.splitlines() if l.strip()), "")
    return ";" if primera_linea.count(";") > primera_linea.count(",") else ","


# ---------------------------------------------------------------------------
# Generación del HTML
# ---------------------------------------------------------------------------
def construir_datos(filas: List[dict], ubicacion: str = "", nombre_csv: str = CSV_POR_DEFECTO) -> Dict[str, object]:
    """Lo único que cambia de un dashboard a otro."""
    return {
        "ubicacion": ubicacion.strip(),
        "csv": nombre_csv,
        "generado": datetime.now().strftime("%d/%m/%Y a las %H:%M"),
        "umbral": UMBRAL_UV,
        "factor": FACTOR,
        "dias": [fila["dia"].isoformat() for fila in filas],
        "uv": [fila["uv"] for fila in filas],
        "uso": [fila["uso"] for fila in filas],
    }


def renderizar(plantilla: str, datos: Dict[str, object]) -> str:
    """Sustituye el marcador de la plantilla por los datos en JSON."""
    if plantilla.count(MARCADOR) != 1:
        raise ErrorDashboard(f"La plantilla tiene que contener el marcador {MARCADOR} una sola vez.")
    json_datos = json.dumps(datos, ensure_ascii=False)
    # Se escapan <, > y & para que ningún texto (por ejemplo, "</script>" en --ubicacion)
    # pueda cerrar la etiqueta <script> donde van los datos.
    json_datos = json_datos.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    return plantilla.replace(MARCADOR, json_datos)


def generar_dashboard(ruta_csv, ruta_html, ubicacion: str = "") -> Tuple[List[dict], List[str]]:
    """Paso 5 completo: CSV -> datos validados -> plantilla -> HTML."""
    filas, avisos = leer_csv(ruta_csv)
    if not PLANTILLA.is_file():
        raise ErrorDashboard(f"No se encuentra la plantilla {PLANTILLA.name}; tiene que estar junto a este script.")
    plantilla = PLANTILLA.read_text(encoding="utf-8")
    html = renderizar(plantilla, construir_datos(filas, ubicacion, Path(ruta_csv).name))
    Path(ruta_html).write_text(html, encoding="utf-8")
    return filas, avisos


# ---------------------------------------------------------------------------
# Línea de comandos
# ---------------------------------------------------------------------------
def leer_argumentos(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        add_help=False,
        description="Genera el dashboard HTML (ECharts) a partir del CSV de protección solar.",
    )
    parser.add_argument("-h", "--help", action="help", help="muestra esta ayuda y termina")
    parser.add_argument("--csv", default=CSV_POR_DEFECTO, metavar="RUTA", help=f"CSV que se lee (por defecto, {CSV_POR_DEFECTO})")
    parser.add_argument("--salida", default=HTML_POR_DEFECTO, metavar="RUTA", help=f"HTML que se genera (por defecto, {HTML_POR_DEFECTO})")
    parser.add_argument("--ubicacion", default="", metavar="TEXTO", help='localidad que aparece en la cabecera, por ejemplo "Madrid, España"')
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = leer_argumentos(argv)
    try:
        filas, avisos = generar_dashboard(args.csv, args.salida, args.ubicacion)
    except ErrorDashboard as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    except OSError as error:
        consejo = " Si está abierto en otro programa, ciérralo y vuelve a intentarlo." if isinstance(error, PermissionError) else ""
        print(f"Error: {error.strerror or error} ({error.filename}).{consejo}", file=sys.stderr)
        return 1

    for aviso in avisos:
        print(f"Aviso, {aviso}")
    primero, ultimo = filas[0]["dia"], filas[-1]["dia"]
    print(f"Dashboard generado en {args.salida}: {len(filas)} días, del {primero:%d/%m/%Y} al {ultimo:%d/%m/%Y}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
