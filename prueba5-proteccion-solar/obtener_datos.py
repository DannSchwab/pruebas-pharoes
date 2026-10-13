#!/usr/bin/env python3
"""Prueba 5 - Pasos 1 a 3.

1. Pide a Open-Meteo el índice UV máximo de cada día de los próximos 7 días.
2. Calcula el uso estimado de protección solar de cada día.
3. Guarda el resultado en un CSV.

Ejemplos:
    python obtener_datos.py --ciudad Madrid
    python obtener_datos.py --ciudad Madrid --pais CO
    python obtener_datos.py --lat 40.4165 --lon -3.70256 --salida madrid.csv

Solo usa la biblioteca estándar de Python (3.8 o superior).
"""

import argparse
import csv
import json
import math
import socket
import sys
from datetime import date
from typing import Dict, List, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

# ---------------------------------------------------------------------------
# Formato del CSV y fórmula. generar_dashboard.py importa estos valores,
# así que solo están definidos aquí.
# ---------------------------------------------------------------------------
COL_DIA = "Día"
COL_UV = "Índice UV máximo"
COL_USO = "Uso estimado de protección solar"
COLUMNAS = (COL_DIA, COL_UV, COL_USO)

UMBRAL_UV = 3  # desde este índice UV se estima uso de protección solar
FACTOR = 5     # uso estimado = (índice UV - UMBRAL_UV) x FACTOR

# ---------------------------------------------------------------------------
# API de Open-Meteo: gratuita y sin clave para uso no comercial.
# ---------------------------------------------------------------------------
URL_GEOCODIFICACION = "https://geocoding-api.open-meteo.com/v1/search"
URL_PREVISION = "https://api.open-meteo.com/v1/forecast"
VARIABLE_UV = "uv_index_max"  # índice UV máximo del día, con la nubosidad prevista
DIAS_POR_DEFECTO = 7
DIAS_MAXIMOS = 16             # límite de la API
SEGUNDOS_ESPERA = 20
CSV_POR_DEFECTO = "proteccion_solar.csv"


class ErrorDatos(Exception):
    """Error con un mensaje pensado para el usuario (se muestra sin traza)."""


# ---------------------------------------------------------------------------
# Paso 2: la fórmula
# ---------------------------------------------------------------------------
def calcular_uso_proteccion(indice_uv: float) -> float:
    """Uso estimado de protección solar de un día.

    - Si el índice UV es 3 o más: (índice UV - 3) x 5
    - Si es menor que 3: 0

    Se redondea a 2 decimales porque, en coma flotante,
    (4.35 - 3) * 5 da 6.749999999999998 en lugar de 6.75.
    """
    indice_uv = float(indice_uv)
    if not math.isfinite(indice_uv) or indice_uv < 0:
        raise ValueError(f"Índice UV no válido: {indice_uv}")
    if indice_uv >= UMBRAL_UV:
        return round((indice_uv - UMBRAL_UV) * FACTOR, 2)
    return 0.0


# ---------------------------------------------------------------------------
# Paso 1: datos de la API
# ---------------------------------------------------------------------------
def pedir_json(url: str, parametros: Dict[str, object]) -> dict:
    """Hace una petición GET y devuelve la respuesta JSON.

    Los problemas de red se convierten en ErrorDatos con un mensaje claro.
    """
    peticion = Request(
        url + "?" + urlencode(parametros),
        headers={"User-Agent": "prueba5-proteccion-solar/1.0"},
    )
    try:
        with urlopen(peticion, timeout=SEGUNDOS_ESPERA) as respuesta:
            datos = json.loads(respuesta.read().decode("utf-8"))
    except HTTPError as error:  # la API responde, pero con un error
        raise ErrorDatos(f"La API ha respondido con el error {error.code}: {_motivo(error)}") from None
    except URLError as error:  # no se ha podido conectar
        if "CERTIFICATE_VERIFY_FAILED" in str(error.reason):
            raise ErrorDatos(
                "No se ha podido verificar el certificado HTTPS de la API. En macOS, ejecuta una vez "
                '"Install Certificates.command", en la carpeta de Python dentro de Aplicaciones.'
            ) from None
        raise ErrorDatos(
            f"No se ha podido conectar con la API ({error.reason}). Comprueba la conexión a internet."
        ) from None
    except socket.timeout:
        raise ErrorDatos(f"La API no ha respondido en {SEGUNDOS_ESPERA} segundos. Vuelve a intentarlo.") from None
    except ValueError:  # JSON mal formado o texto que no es UTF-8
        raise ErrorDatos("La API ha devuelto una respuesta que no es JSON.") from None

    if not isinstance(datos, dict):
        raise ErrorDatos("La API ha devuelto una respuesta con un formato inesperado.")
    return datos


def _motivo(error: HTTPError) -> str:
    """Open-Meteo explica sus errores en un JSON como {"error": true, "reason": "..."}."""
    try:
        return str(json.loads(error.read().decode("utf-8"))["reason"])
    except Exception:  # si no viene el JSON, sirve el texto estándar del código HTTP
        return str(error.reason)


def buscar_localidad(ciudad: str, pais: Optional[str] = None) -> dict:
    """Convierte el nombre de una localidad en coordenadas (API de geocodificación).

    La API ordena los resultados por relevancia, así que se usa el primero
    (o el primero del país indicado con --pais).
    """
    datos = pedir_json(URL_GEOCODIFICACION, {"name": ciudad, "count": 10, "language": "es", "format": "json"})
    candidatas = datos.get("results") or []
    if pais:
        candidatas = [c for c in candidatas if str(c.get("country_code", "")).upper() == pais.upper()]
    if not candidatas:
        en_pais = f" en el país {pais.upper()}" if pais else ""
        raise ErrorDatos(f'No se ha encontrado la localidad "{ciudad}"{en_pais}. Revisa el nombre o usa --lat y --lon.')

    elegida = candidatas[0]
    try:
        latitud, longitud = float(elegida["latitude"]), float(elegida["longitude"])
    except (KeyError, TypeError, ValueError):
        raise ErrorDatos("La API de geocodificación ha devuelto una localidad sin coordenadas.") from None

    otros_paises = {c.get("country_code") for c in candidatas[1:]} - {elegida.get("country_code"), None}
    return {
        "nombre": elegida.get("name") or ciudad,
        "region": elegida.get("admin1"),
        "pais": elegida.get("country"),
        "latitud": latitud,
        "longitud": longitud,
        "otros_paises": sorted(otros_paises),
    }


def obtener_indice_uv(latitud: float, longitud: float, dias: int = DIAS_POR_DEFECTO) -> List[Tuple[str, float]]:
    """Paso 1: índice UV máximo de cada día, como lista de (fecha "aaaa-mm-dd", índice UV).

    Con timezone=auto cada día va de 0:00 a 24:00 en la hora local de la localidad.
    """
    datos = pedir_json(URL_PREVISION, {
        "latitude": latitud,
        "longitude": longitud,
        "daily": VARIABLE_UV,
        "timezone": "auto",
        "forecast_days": dias,
    })
    return leer_prevision(datos)


def leer_prevision(datos: dict) -> List[Tuple[str, float]]:
    """Saca los días y el índice UV de la respuesta de la API y comprueba que son válidos."""
    diario = datos.get("daily") or {}
    fechas = diario.get("time")
    valores = diario.get(VARIABLE_UV)
    if not isinstance(fechas, list) or not isinstance(valores, list) or not fechas or len(fechas) != len(valores):
        raise ErrorDatos(f"La respuesta de la API no tiene el formato esperado (daily.time y daily.{VARIABLE_UV}).")

    # Un dato que falta no se convierte en 0: daría un uso estimado falso.
    sin_dato = [str(fecha) for fecha, valor in zip(fechas, valores) if valor is None]
    if sin_dato:
        raise ErrorDatos(
            f"La API no ha devuelto el índice UV de {len(sin_dato)} día(s): {', '.join(sin_dato)}. "
            "No se rellena con 0 porque falsearía el uso estimado. "
            "Prueba con menos días (--dias) o vuelve a intentarlo más tarde."
        )

    dias = []
    for fecha, valor in zip(fechas, valores):
        try:
            date.fromisoformat(fecha)
            indice_uv = float(valor)
        except (TypeError, ValueError):
            raise ErrorDatos(f"Dato no válido en la respuesta de la API: {fecha!r} -> {valor!r}") from None
        if not math.isfinite(indice_uv) or indice_uv < 0:
            raise ErrorDatos(f"Índice UV no válido en la respuesta de la API: {fecha} -> {valor!r}")
        dias.append((fecha, indice_uv))
    return dias


# ---------------------------------------------------------------------------
# Paso 3: el CSV
# ---------------------------------------------------------------------------
def calcular_filas(dias: List[Tuple[str, float]]) -> List[dict]:
    """Aplica el paso 2 a cada día."""
    return [
        {COL_DIA: fecha, COL_UV: indice_uv, COL_USO: calcular_uso_proteccion(indice_uv)}
        for fecha, indice_uv in dias
    ]


def formatear_numero(valor: float) -> str:
    """Número con punto decimal y sin ceros de más: 5.0 -> "5", 4.35 -> "4.35"."""
    valor = float(valor)
    return str(int(valor)) if valor.is_integer() else repr(valor)


def guardar_csv(filas: List[dict], ruta: str) -> None:
    """Guarda las columnas Día, Índice UV máximo y Uso estimado de protección solar.

    Se escribe en UTF-8 con BOM para que Excel muestre bien las tildes.
    """
    with open(ruta, "w", newline="", encoding="utf-8-sig") as fichero:
        escritor = csv.writer(fichero)
        escritor.writerow(COLUMNAS)
        for fila in filas:
            escritor.writerow([fila[COL_DIA], formatear_numero(fila[COL_UV]), formatear_numero(fila[COL_USO])])


# ---------------------------------------------------------------------------
# Línea de comandos
# ---------------------------------------------------------------------------
def leer_argumentos(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        add_help=False,
        description="Obtiene el índice UV máximo de los próximos días (Open-Meteo), "
                    "calcula el uso estimado de protección solar y lo guarda en un CSV.",
    )
    parser.add_argument("-h", "--help", action="help", help="muestra esta ayuda y termina")
    parser.add_argument("--ciudad", default="Madrid", metavar="NOMBRE", help="localidad que se consulta (por defecto, Madrid)")
    parser.add_argument("--pais", metavar="CÓDIGO", help="código del país (ES, CO, MX...) si hay localidades con el mismo nombre")
    parser.add_argument("--lat", type=float, metavar="GRADOS", help="latitud, en lugar de --ciudad")
    parser.add_argument("--lon", type=float, metavar="GRADOS", help="longitud, en lugar de --ciudad")
    parser.add_argument("--dias", type=int, default=DIAS_POR_DEFECTO, metavar="N",
                        help=f"días de previsión, de 1 a {DIAS_MAXIMOS} (por defecto, {DIAS_POR_DEFECTO})")
    parser.add_argument("--salida", default=CSV_POR_DEFECTO, metavar="RUTA", help=f"CSV que se genera (por defecto, {CSV_POR_DEFECTO})")
    args = parser.parse_args(argv)

    if (args.lat is None) != (args.lon is None):
        parser.error("--lat y --lon tienen que usarse juntas")
    if args.lat is not None and not (-90 <= args.lat <= 90 and -180 <= args.lon <= 180):
        parser.error("coordenadas fuera de rango (latitud de -90 a 90 y longitud de -180 a 180)")
    if not 1 <= args.dias <= DIAS_MAXIMOS:
        parser.error(f"--dias tiene que estar entre 1 y {DIAS_MAXIMOS}")
    return args


def mostrar_tabla(filas: List[dict]) -> None:
    print(f"\n{'Día':<12}{'Índice UV máximo':>18}{'Uso estimado':>15}")
    for fila in filas:
        print(f"{fila[COL_DIA]:<12}{formatear_numero(fila[COL_UV]):>18}{formatear_numero(fila[COL_USO]):>15}")


def main(argv: Optional[List[str]] = None) -> int:
    args = leer_argumentos(argv)
    try:
        if args.lat is not None:
            latitud, longitud = args.lat, args.lon
            ubicacion = f"{latitud}, {longitud}"
            print(f"Coordenadas: {ubicacion}")
        else:
            localidad = buscar_localidad(args.ciudad, args.pais)
            latitud, longitud = localidad["latitud"], localidad["longitud"]
            ubicacion = ", ".join(p for p in (localidad["nombre"], localidad["pais"]) if p)
            detalle = ", ".join(p for p in (localidad["region"], localidad["pais"]) if p)
            print(f"Localidad: {localidad['nombre']} ({detalle}) - {latitud}, {longitud}")
            if localidad["otros_paises"]:
                print(f"  Hay localidades con el mismo nombre en {', '.join(localidad['otros_paises'])}. "
                      "Para elegir otra, usa --pais.")
        dias = obtener_indice_uv(latitud, longitud, args.dias)
    except ErrorDatos as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    filas = calcular_filas(dias)
    try:
        guardar_csv(filas, args.salida)
    except OSError as error:
        consejo = " Si está abierto en Excel, ciérralo y vuelve a intentarlo." if isinstance(error, PermissionError) else ""
        print(f"Error: no se ha podido guardar {args.salida} ({error.strerror or error}).{consejo}", file=sys.stderr)
        return 1

    mostrar_tabla(filas)
    print(f"\nCSV guardado en {args.salida}")
    siguiente = "python generar_dashboard.py"
    if args.salida != CSV_POR_DEFECTO:
        siguiente += f' --csv "{args.salida}"'
    print(f'Siguiente paso: {siguiente} --ubicacion "{ubicacion}"')
    return 0


if __name__ == "__main__":
    sys.exit(main())
