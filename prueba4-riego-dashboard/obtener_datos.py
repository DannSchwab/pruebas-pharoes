#!/usr/bin/env python3
"""Pasos 1, 2 y 3: precipitación prevista -> uso estimado de riego -> CSV.

1. Pide a la API de Open-Meteo la precipitación diaria prevista (mm) de los
   próximos días para una localidad (por nombre o por coordenadas).
2. Calcula el uso estimado de riego de cada día:
       precipitación <= 5 mm  ->  uso = (5 - precipitación) x 10
       precipitación  > 5 mm  ->  uso = 0
3. Guarda el resultado en un CSV con las columnas
   "Día", "Precipitación (mm)" y "Uso estimado de riego".

Solo usa la biblioteca estándar de Python: no hay que instalar nada.

Ejemplos:
    python obtener_datos.py                          # Madrid, 7 días -> riego.csv
    python obtener_datos.py --ciudad Sevilla
    python obtener_datos.py --ciudad Valencia --pais ES
    python obtener_datos.py --lat 41.65 --lon -0.88 --salida zaragoza.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

URL_GEOCODIFICACION = "https://geocoding-api.open-meteo.com/v1/search"
URL_PREVISION = "https://api.open-meteo.com/v1/forecast"

# Datos de la fórmula del enunciado, definidos en un único sitio
# (generar_dashboard.py también los usa).
UMBRAL_MM = 5  # con más precipitación que esta no hace falta regar
FACTOR = 10  # multiplicador de la fórmula

# Cabecera del CSV, en este orden.
COLUMNAS = ("Día", "Precipitación (mm)", "Uso estimado de riego")


class ErrorDatos(Exception):
    """Fallo al obtener los datos que se explica al usuario sin mostrar la traza."""


# --------------------------------------------------------------------------
# Paso 2: la fórmula
# --------------------------------------------------------------------------
def calcular_uso_riego(precipitacion_mm: float) -> float:
    """Devuelve el uso estimado de riego de un día según su precipitación (mm)."""
    if precipitacion_mm < 0:
        raise ValueError(f"precipitación negativa: {precipitacion_mm}")
    if precipitacion_mm <= UMBRAL_MM:
        # round() quita los restos de la coma flotante: (5 - 4.05) * 10 = 9.500000000000002
        return round((UMBRAL_MM - precipitacion_mm) * FACTOR, 2)
    return 0.0


def calcular_filas(precipitaciones: list[tuple[str, float]]) -> list[tuple[str, float, float]]:
    """Añade a cada (día, precipitación) su uso estimado de riego."""
    return [(dia, mm, calcular_uso_riego(mm)) for dia, mm in precipitaciones]


# --------------------------------------------------------------------------
# Paso 1: la API
# --------------------------------------------------------------------------
def pedir_json(url: str, parametros: dict) -> dict:
    """Hace una petición GET y devuelve la respuesta JSON como diccionario."""
    direccion = f"{url}?{urllib.parse.urlencode(parametros)}"
    peticion = urllib.request.Request(direccion, headers={"User-Agent": "prueba-riego-dashboard/1.0"})
    try:
        with urllib.request.urlopen(peticion, timeout=20) as respuesta:
            return json.load(respuesta)
    except urllib.error.HTTPError as error:
        # Open-Meteo explica el fallo en el campo "reason" de la respuesta.
        try:
            motivo = json.load(error)["reason"]
        except (ValueError, KeyError, TypeError):
            motivo = error.reason
        raise ErrorDatos(f"la API respondió con el error {error.code}: {motivo}") from None
    except OSError as error:  # sin conexión, DNS, certificados, tiempo agotado...
        motivo = getattr(error, "reason", error)
        raise ErrorDatos(f"no se pudo conectar con {url} ({motivo})") from None
    except ValueError:
        raise ErrorDatos(f"la respuesta de {url} no es un JSON válido") from None


def buscar_localidad(nombre: str, pais: str | None = None) -> dict:
    """Convierte el nombre de una localidad en coordenadas (API de geocodificación)."""
    parametros = {"name": nombre, "count": 1, "language": "es", "format": "json"}
    if pais:
        parametros["countryCode"] = pais.upper()
    resultados = pedir_json(URL_GEOCODIFICACION, parametros).get("results")
    if not resultados:
        raise ErrorDatos(f'no se ha encontrado la localidad "{nombre}"')
    lugar = resultados[0]
    return {
        "nombre": ", ".join(p for p in (lugar.get("name"), lugar.get("country")) if p),
        "region": lugar.get("admin1", ""),
        "latitud": lugar["latitude"],
        "longitud": lugar["longitude"],
    }


def obtener_precipitacion(latitud: float, longitud: float, dias: int = 7) -> list[tuple[str, float]]:
    """Devuelve [(día, precipitación en mm), ...] para los próximos `dias` días."""
    datos = pedir_json(URL_PREVISION, {
        "latitude": latitud,
        "longitude": longitud,
        "daily": "precipitation_sum",  # total del día: lluvia + chubascos + nieve
        "precipitation_unit": "mm",
        "forecast_days": dias,  # el primero es hoy
        "timezone": "auto",  # los días se cuentan en la hora local de la localidad
    })
    try:
        fechas = datos["daily"]["time"]
        valores = datos["daily"]["precipitation_sum"]
    except (KeyError, TypeError):
        raise ErrorDatos("la respuesta de la API no tiene el formato esperado") from None

    precipitaciones = []
    for dia, mm in zip(fechas, valores):
        if mm is None:  # no se inventa un 0: falsearía el cálculo del riego
            raise ErrorDatos(f"la API no tiene previsión de precipitación para el día {dia}")
        precipitaciones.append((dia, float(mm)))
    return precipitaciones


# --------------------------------------------------------------------------
# Paso 3: el CSV
# --------------------------------------------------------------------------
def guardar_csv(filas: list[tuple[str, float, float]], ruta: str) -> None:
    """Escribe el CSV con la cabecera COLUMNAS y dos decimales por valor.

    Se guarda en UTF-8 con BOM ("utf-8-sig") para que Excel reconozca la
    codificación y muestre bien las tildes de las cabeceras.
    """
    with open(ruta, "w", newline="", encoding="utf-8-sig") as fichero:
        escritor = csv.writer(fichero)
        escritor.writerow(COLUMNAS)
        for dia, precipitacion, uso in filas:
            escritor.writerow([dia, f"{precipitacion:.2f}", f"{uso:.2f}"])


def mostrar_resumen(localidad: dict, filas: list[tuple[str, float, float]], ruta_csv: str) -> None:
    """Muestra en la consola lo que se ha guardado y el siguiente paso."""
    region = f" ({localidad['region']})" if localidad.get("region") else ""
    print(f"Localidad: {localidad['nombre']}{region}, "
          f"coordenadas {localidad['latitud']}, {localidad['longitud']}\n")
    print(f"{COLUMNAS[0]:<12}{COLUMNAS[1]:>20}{COLUMNAS[2]:>25}")
    for dia, precipitacion, uso in filas:
        print(f"{dia:<12}{precipitacion:>20.2f}{uso:>25.2f}")
    print(f"\nCSV guardado en {ruta_csv}")
    print(f'Siguiente paso: python generar_dashboard.py --csv "{ruta_csv}" '
          f'--ubicacion "{localidad["nombre"]}"')


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Descarga la precipitación prevista de una localidad y calcula "
                    "el uso estimado de riego de cada día.")
    parser.add_argument("--ciudad", default="Madrid",
                        help="localidad a consultar (por defecto: Madrid)")
    parser.add_argument("--pais",
                        help="código de país de dos letras para desambiguar la ciudad, p. ej. ES")
    parser.add_argument("--lat", type=float, help="latitud, en lugar de --ciudad")
    parser.add_argument("--lon", type=float, help="longitud, en lugar de --ciudad")
    parser.add_argument("--dias", type=int, default=7,
                        help="días de previsión, de 1 a 16 (por defecto: 7)")
    parser.add_argument("--salida", default="riego.csv",
                        help="ruta del CSV que se genera (por defecto: riego.csv)")
    args = parser.parse_args(argv)

    if (args.lat is None) != (args.lon is None):
        parser.error("--lat y --lon tienen que indicarse juntas")
    if not 1 <= args.dias <= 16:
        parser.error("--dias tiene que estar entre 1 y 16 (límite de Open-Meteo)")

    try:
        if args.lat is not None:
            localidad = {"nombre": f"{args.lat}, {args.lon}", "latitud": args.lat, "longitud": args.lon}
        else:
            localidad = buscar_localidad(args.ciudad, args.pais)
        precipitaciones = obtener_precipitacion(localidad["latitud"], localidad["longitud"], args.dias)
    except ErrorDatos as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    filas = calcular_filas(precipitaciones)
    guardar_csv(filas, args.salida)
    mostrar_resumen(localidad, filas, args.salida)
    return 0


if __name__ == "__main__":
    sys.exit(main())
