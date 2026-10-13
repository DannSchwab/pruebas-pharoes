#!/usr/bin/env python3
"""Paso 5: genera automáticamente el dashboard HTML (paso 4) a partir del CSV.

Lee el CSV, mete sus datos en plantilla_dashboard.html y escribe el HTML final.
El HTML generado no se edita nunca a mano: si cambia el CSV, basta con volver a
ejecutar este script.

Ejemplos:
    python generar_dashboard.py
    python generar_dashboard.py --ubicacion "Madrid, España"
    python generar_dashboard.py --csv zaragoza.csv --salida zaragoza.html
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import math
import sys
from datetime import datetime
from pathlib import Path

# El formato del CSV y la fórmula se definen una sola vez, en obtener_datos.py.
from obtener_datos import COLUMNAS, FACTOR, UMBRAL_MM

PLANTILLA = Path(__file__).with_name("plantilla_dashboard.html")
MARCADOR = "__DATOS_JSON__"  # texto de la plantilla que se sustituye por los datos

COL_DIA, COL_PRECIPITACION, COL_USO = COLUMNAS

DIAS_SEMANA = ("lun", "mar", "mié", "jue", "vie", "sáb", "dom")
MESES = ("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic")


class ErrorCSV(Exception):
    """Problema en el contenido del CSV, explicado para el usuario."""


def leer_texto(ruta: Path) -> str:
    """Lee el fichero en UTF-8 (con o sin BOM) o, si no lo es, en la codificación de Excel en Windows."""
    try:
        return ruta.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        return ruta.read_text(encoding="cp1252")


def a_numero(valor: str | None, linea: int, columna: str) -> float:
    """Convierte un valor del CSV en número; admite coma decimal ("4,05")."""
    texto = (valor or "").strip().replace(",", ".")
    try:
        numero = float(texto)
    except ValueError:
        numero = math.nan
    if not math.isfinite(numero):
        raise ErrorCSV(f'línea {linea}: "{valor}" no es un número válido en la columna "{columna}"')
    return numero


def leer_csv(ruta: Path) -> list[dict]:
    """Lee y valida el CSV. Devuelve una lista de {"dia", "precipitacion", "uso"}."""
    texto = leer_texto(ruta)
    cabecera = texto.split("\n", 1)[0]
    # Si se guarda desde Excel en español, el separador pasa a ser ";" (y los decimales, ",").
    separador = ";" if cabecera.count(";") > cabecera.count(",") else ","
    lector = csv.DictReader(io.StringIO(texto), delimiter=separador)

    columnas = [nombre.strip() for nombre in (lector.fieldnames or [])]
    faltan = [nombre for nombre in COLUMNAS if nombre not in columnas]
    if faltan:
        raise ErrorCSV(f"faltan las columnas {', '.join(faltan)} "
                       f"(columnas encontradas: {', '.join(columnas) or 'ninguna'})")
    lector.fieldnames = columnas  # cabeceras sin espacios sobrantes

    filas = []
    for fila in lector:
        if not any(isinstance(valor, str) and valor.strip() for valor in fila.values()):
            continue  # línea vacía o solo con separadores
        filas.append({
            "dia": (fila[COL_DIA] or "").strip(),
            "precipitacion": a_numero(fila[COL_PRECIPITACION], lector.line_num, COL_PRECIPITACION),
            "uso": a_numero(fila[COL_USO], lector.line_num, COL_USO),
        })
    if not filas:
        raise ErrorCSV("no hay ninguna fila de datos")
    return filas


def etiqueta_dia(texto: str) -> str:
    """'2026-10-12' -> 'lun 12 oct'. También entiende '12/10/2026'; si no es una fecha, lo deja igual."""
    for formato in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            fecha = datetime.strptime(texto, formato).date()
        except ValueError:
            continue
        return f"{DIAS_SEMANA[fecha.weekday()]} {fecha.day} {MESES[fecha.month - 1]}"
    return texto


def preparar_datos(filas: list[dict], ubicacion: str, origen: str) -> dict:
    """Reúne todo lo que necesita la plantilla en un diccionario."""
    return {
        "columnas": list(COLUMNAS),
        "umbral_mm": UMBRAL_MM,
        "factor": FACTOR,
        "ubicacion": ubicacion,
        "origen": origen,
        "generado": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "dias": [etiqueta_dia(fila["dia"]) for fila in filas],
        "precipitacion": [fila["precipitacion"] for fila in filas],
        "uso": [fila["uso"] for fila in filas],
    }


def generar_html(datos: dict, plantilla: str) -> str:
    """Sustituye el marcador de la plantilla por los datos en formato JSON."""
    if plantilla.count(MARCADOR) != 1:
        raise ValueError(f"la plantilla tiene que contener el marcador {MARCADOR} una sola vez")
    # Un JSON es un literal válido de JavaScript. Se escapa "<" para que ningún texto
    # del CSV pueda cerrar la etiqueta <script> antes de tiempo.
    datos_json = json.dumps(datos, ensure_ascii=False, indent=2).replace("<", "\\u003c")
    return plantilla.replace(MARCADOR, datos_json)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Genera el dashboard HTML a partir del CSV de riego.")
    parser.add_argument("--csv", type=Path, default=Path("riego.csv"),
                        help="CSV de entrada (por defecto: riego.csv)")
    parser.add_argument("--salida", type=Path, default=Path("dashboard.html"),
                        help="HTML que se genera (por defecto: dashboard.html)")
    parser.add_argument("--ubicacion", default="",
                        help='localidad que se muestra en la cabecera, p. ej. "Madrid, España"')
    args = parser.parse_args(argv)

    try:
        filas = leer_csv(args.csv)
    except FileNotFoundError:
        print(f"Error: no existe {args.csv}. Genera antes el CSV con obtener_datos.py", file=sys.stderr)
        return 1
    except ErrorCSV as error:
        print(f"Error en {args.csv}: {error}", file=sys.stderr)
        return 1

    datos = preparar_datos(filas, args.ubicacion.strip(), args.csv.name)
    html = generar_html(datos, PLANTILLA.read_text(encoding="utf-8"))
    args.salida.write_text(html, encoding="utf-8")
    print(f"Dashboard generado en {args.salida} con {len(filas)} días de {args.csv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
