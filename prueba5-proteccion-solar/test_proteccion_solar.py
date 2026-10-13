"""Pruebas automáticas de la Prueba 5. No necesitan internet.

Ejecución:
    python -m unittest -v
"""

import io
import json
import math
import re
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import date
from pathlib import Path
from unittest import mock
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))

import generar_dashboard as gd  # noqa: E402
import obtener_datos as od  # noqa: E402

# Respuesta real de la API de geocodificación para "Madrid" (consultada el 13/10/2026),
# recortada a los 5 primeros resultados y a los campos que interesan.
RESPUESTA_GEOCODIFICACION = """{"results":[
{"id":3117735,"name":"Madrid","latitude":40.4165,"longitude":-3.70256,"elevation":665.0,"country_code":"ES","timezone":"Europe/Madrid","country":"España","admin1":"Comunidad Autónoma de Madrid"},
{"id":3675707,"name":"Madrid","latitude":4.73245,"longitude":-74.26419,"elevation":2547.0,"country_code":"CO","timezone":"America/Bogota","country":"Colombia","admin1":"Cundinamarca"},
{"id":1704129,"name":"Madrid","latitude":9.26211,"longitude":125.96437,"elevation":19.0,"country_code":"PH","timezone":"Asia/Manila","country":"Filipinas","admin1":"Caraga"},
{"id":4865871,"name":"Madrid","latitude":41.87665,"longitude":-93.82328,"elevation":310.0,"country_code":"US","timezone":"America/Chicago","country":"Estados Unidos","admin1":"Iowa"},
{"id":5125646,"name":"Madrid","latitude":44.75034,"longitude":-75.13104,"elevation":99.0,"country_code":"US","timezone":"America/New_York","country":"Estados Unidos","admin1":"Nueva York"}
],"generationtime_ms":0.32043457}"""

# Respuesta con el formato de la API de previsión de Open-Meteo (daily=uv_index_max,
# timezone=auto, forecast_days=7). Los valores son de ejemplo.
RESPUESTA_PREVISION = """{"latitude":40.4375,"longitude":-3.6875,"generationtime_ms":0.06,
"utc_offset_seconds":7200,"timezone":"Europe/Madrid","timezone_abbreviation":"GMT+2","elevation":665.0,
"daily_units":{"time":"iso8601","uv_index_max":""},
"daily":{"time":["2026-10-13","2026-10-14","2026-10-15","2026-10-16","2026-10-17","2026-10-18","2026-10-19"],
"uv_index_max":[4.15,4.35,3.85,2.6,3.45,4.05,4.2]}}"""

UV_EJEMPLO = [4.15, 4.35, 3.85, 2.6, 3.45, 4.05, 4.2]
USO_EJEMPLO = [5.75, 6.75, 4.25, 0.0, 2.25, 5.25, 6.0]


def api_falsa(peticiones, prevision=RESPUESTA_PREVISION, geocodificacion=RESPUESTA_GEOCODIFICACION):
    """Sustituye a urlopen: responde con las respuestas guardadas y apunta las URL pedidas."""
    def urlopen_falso(peticion, timeout=None):
        url = peticion.full_url
        peticiones.append(url)
        if url.startswith(od.URL_PREVISION):
            return io.BytesIO(prevision.encode("utf-8"))
        if url.startswith(od.URL_GEOCODIFICACION):
            return io.BytesIO(geocodificacion.encode("utf-8"))
        raise AssertionError(f"URL inesperada: {url}")
    return urlopen_falso


def parametros(url):
    return {clave: valores[0] for clave, valores in parse_qs(urlparse(url).query).items()}


def datos_del_html(html):
    """Extrae y decodifica el JSON que el generador inserta en el HTML."""
    bloque = re.search(r'<script id="datos-dashboard" type="application/json">(.*?)</script>', html, re.S)
    return json.loads(bloque.group(1))


class FormulaTest(unittest.TestCase):
    def test_por_debajo_del_umbral_el_uso_es_cero(self):
        for uv in (0, 1.5, 2.99):
            self.assertEqual(od.calcular_uso_proteccion(uv), 0)

    def test_en_el_umbral_el_uso_es_cero(self):
        self.assertEqual(od.calcular_uso_proteccion(3), 0)

    def test_por_encima_del_umbral(self):
        for uv, esperado in ((3.01, 0.05), (4, 5), (4.35, 6.75), (8, 25), (11, 40), (13.5, 52.5)):
            with self.subTest(uv=uv):
                self.assertEqual(od.calcular_uso_proteccion(uv), esperado)

    def test_sin_restos_de_coma_flotante(self):
        self.assertEqual((4.35 - 3) * 5, 6.749999999999998)  # el problema que se evita
        self.assertEqual(repr(od.calcular_uso_proteccion(4.35)), "6.75")
        self.assertEqual(repr(od.calcular_uso_proteccion(4.05)), "5.25")

    def test_indice_no_valido(self):
        for uv in (-1, math.nan, math.inf):
            with self.subTest(uv=uv), self.assertRaises(ValueError):
                od.calcular_uso_proteccion(uv)


class ApiTest(unittest.TestCase):
    def test_peticion_de_la_prevision(self):
        peticiones = []
        with mock.patch.object(od, "urlopen", api_falsa(peticiones)):
            od.obtener_indice_uv(40.4165, -3.70256)
        consulta = parametros(peticiones[0])
        self.assertEqual(consulta["daily"], "uv_index_max")
        self.assertEqual(consulta["forecast_days"], "7")
        self.assertEqual(consulta["timezone"], "auto")
        self.assertEqual((consulta["latitude"], consulta["longitude"]), ("40.4165", "-3.70256"))

    def test_lee_los_siete_dias(self):
        with mock.patch.object(od, "urlopen", api_falsa([])):
            dias = od.obtener_indice_uv(40.4165, -3.70256)
        self.assertEqual([fecha for fecha, _ in dias][:2], ["2026-10-13", "2026-10-14"])
        self.assertEqual([uv for _, uv in dias], UV_EJEMPLO)

    def test_un_dato_que_falta_no_se_convierte_en_cero(self):
        respuesta = json.loads(RESPUESTA_PREVISION)
        respuesta["daily"]["uv_index_max"][3] = None
        with self.assertRaises(od.ErrorDatos) as contexto:
            od.leer_prevision(respuesta)
        self.assertIn("2026-10-16", str(contexto.exception))

    def test_respuesta_con_formato_inesperado(self):
        for respuesta in ({}, {"daily": {"time": ["2026-10-13"]}}, {"daily": {"time": ["2026-10-13"], "uv_index_max": [-2]}}):
            with self.subTest(respuesta=respuesta), self.assertRaises(od.ErrorDatos):
                od.leer_prevision(respuesta)

    def test_error_de_la_api_se_explica(self):
        cuerpo = io.BytesIO(b'{"error":true,"reason":"Latitude must be in range of -90 to 90\xc2\xb0."}')

        def urlopen_con_error(peticion, timeout=None):
            raise HTTPError(peticion.full_url, 400, "Bad Request", {}, cuerpo)

        with mock.patch.object(od, "urlopen", urlopen_con_error), self.assertRaises(od.ErrorDatos) as contexto:
            od.obtener_indice_uv(40.4, -3.7)
        self.assertIn("400", str(contexto.exception))
        self.assertIn("Latitude must be in range", str(contexto.exception))

    def test_geocodificacion(self):
        peticiones = []
        with mock.patch.object(od, "urlopen", api_falsa(peticiones)):
            localidad = od.buscar_localidad("Madrid")
        self.assertEqual((localidad["latitud"], localidad["longitud"]), (40.4165, -3.70256))
        self.assertEqual(localidad["pais"], "España")
        self.assertEqual(localidad["otros_paises"], ["CO", "PH", "US"])
        self.assertEqual(parametros(peticiones[0])["name"], "Madrid")

    def test_geocodificacion_con_pais(self):
        with mock.patch.object(od, "urlopen", api_falsa([])):
            localidad = od.buscar_localidad("Madrid", pais="co")
        self.assertEqual((localidad["latitud"], localidad["longitud"]), (4.73245, -74.26419))

    def test_localidad_no_encontrada(self):
        with mock.patch.object(od, "urlopen", api_falsa([], geocodificacion='{"generationtime_ms":0.2}')):
            with self.assertRaises(od.ErrorDatos):
                od.buscar_localidad("Xyzzyx")


class CsvTest(unittest.TestCase):
    def setUp(self):
        self.carpeta = tempfile.TemporaryDirectory()
        self.dir = Path(self.carpeta.name)

    def tearDown(self):
        self.carpeta.cleanup()

    def test_formato_del_csv(self):
        ruta = self.dir / "uv.csv"
        dias = [("2026-10-13", 4.35), ("2026-10-16", 2.6), ("2026-10-17", 5.0)]
        od.guardar_csv(od.calcular_filas(dias), ruta)
        contenido = ruta.read_bytes()
        self.assertTrue(contenido.startswith(b"\xef\xbb\xbf"))  # BOM para Excel
        lineas = contenido.decode("utf-8-sig").splitlines()
        self.assertEqual(lineas[0], "Día,Índice UV máximo,Uso estimado de protección solar")
        self.assertEqual(lineas[1:], ["2026-10-13,4.35,6.75", "2026-10-16,2.6,0", "2026-10-17,5,10"])

    def test_de_la_api_al_csv(self):
        ruta = self.dir / "proteccion_solar.csv"
        salida = io.StringIO()
        with mock.patch.object(od, "urlopen", api_falsa([])), redirect_stdout(salida):
            codigo = od.main(["--ciudad", "Madrid", "--salida", str(ruta)])
        self.assertEqual(codigo, 0)
        filas, avisos = gd.leer_csv(ruta)
        self.assertEqual([f["uv"] for f in filas], UV_EJEMPLO)
        self.assertEqual([f["uso"] for f in filas], USO_EJEMPLO)
        self.assertEqual(avisos, [])
        self.assertIn('--ubicacion "Madrid, España"', salida.getvalue())

    def test_csv_guardado_desde_excel_en_espanol(self):
        ruta = self.dir / "excel.csv"
        texto = ("Día;Índice UV máximo;Uso estimado de protección solar\r\n"
                 "13/10/2026;4,35;6,75\r\n14/10/2026;2,6;0\r\n;;\r\n")
        ruta.write_bytes(texto.encode("cp1252"))
        filas, avisos = gd.leer_csv(ruta)
        self.assertEqual(filas, [
            {"dia": date(2026, 10, 13), "uv": 4.35, "uso": 6.75},
            {"dia": date(2026, 10, 14), "uv": 2.6, "uso": 0.0},
        ])
        self.assertEqual(avisos, [])

    def test_errores_en_el_csv(self):
        cabecera = "Día,Índice UV máximo,Uso estimado de protección solar\n"
        casos = {
            "falta una columna": ("Día,Índice UV máximo\n2026-10-13,4.35\n", "Faltan columnas"),
            "valor vacío": (cabecera + "2026-10-13,,6.75\n", "falta el valor"),
            "no es un número": (cabecera + "2026-10-13,alto,6.75\n", "no es un número"),
            "número negativo": (cabecera + "2026-10-13,-1,0\n", "de 0 en adelante"),
            "fecha no válida": (cabecera + "2026-13-45,4.35,6.75\n", "no es válida"),
            "día repetido": (cabecera + "2026-10-13,4.35,6.75\n2026-10-13,4,5\n", "repetido"),
            "sin filas": (cabecera, "no tiene filas"),
            "vacío": ("", "vacío"),
        }
        for caso, (texto, mensaje) in casos.items():
            with self.subTest(caso=caso):
                ruta = self.dir / "erroneo.csv"
                ruta.write_text(texto, encoding="utf-8")
                with self.assertRaises(gd.ErrorDashboard) as contexto:
                    gd.leer_csv(ruta)
                self.assertIn(mensaje, str(contexto.exception))

    def test_aviso_si_el_uso_no_cuadra_con_la_formula(self):
        ruta = self.dir / "editado.csv"
        ruta.write_text("Día,Índice UV máximo,Uso estimado de protección solar\n2026-10-13,4.35,9\n", encoding="utf-8")
        filas, avisos = gd.leer_csv(ruta)
        self.assertEqual(filas[0]["uso"], 9)  # se respeta el CSV...
        self.assertEqual(len(avisos), 1)      # ...pero se avisa
        self.assertIn("6.75", avisos[0])

    def test_los_dias_se_ordenan(self):
        ruta = self.dir / "desordenado.csv"
        ruta.write_text("Día,Índice UV máximo,Uso estimado de protección solar\n"
                        "2026-10-15,3.85,4.25\n2026-10-13,4.15,5.75\n", encoding="utf-8")
        filas, _ = gd.leer_csv(ruta)
        self.assertEqual([f["dia"].day for f in filas], [13, 15])


class DashboardTest(unittest.TestCase):
    def setUp(self):
        self.carpeta = tempfile.TemporaryDirectory()
        self.dir = Path(self.carpeta.name)
        self.csv = self.dir / "proteccion_solar.csv"
        self.html = self.dir / "dashboard.html"
        dias = json.loads(RESPUESTA_PREVISION)["daily"]
        od.guardar_csv(od.calcular_filas(list(zip(dias["time"], dias["uv_index_max"]))), self.csv)

    def tearDown(self):
        self.carpeta.cleanup()

    def test_el_html_sale_del_csv(self):
        gd.generar_dashboard(self.csv, self.html, "Madrid, España")
        html = self.html.read_text(encoding="utf-8")
        self.assertNotIn(gd.MARCADOR, html)
        datos = datos_del_html(html)
        self.assertEqual(datos["dias"][0], "2026-10-13")
        self.assertEqual(datos["uv"], UV_EJEMPLO)
        self.assertEqual(datos["uso"], USO_EJEMPLO)
        self.assertEqual((datos["umbral"], datos["factor"]), (od.UMBRAL_UV, od.FACTOR))
        self.assertEqual(datos["ubicacion"], "Madrid, España")

    def test_si_cambia_el_csv_cambia_el_dashboard(self):
        gd.generar_dashboard(self.csv, self.html)
        antes = datos_del_html(self.html.read_text(encoding="utf-8"))
        od.guardar_csv(od.calcular_filas([("2026-07-01", 9.5), ("2026-07-02", 10.2)]), self.csv)
        gd.generar_dashboard(self.csv, self.html)
        despues = datos_del_html(self.html.read_text(encoding="utf-8"))
        self.assertEqual(len(antes["dias"]), 7)
        self.assertEqual(despues["dias"], ["2026-07-01", "2026-07-02"])
        self.assertEqual(despues["uso"], [32.5, 36.0])

    def test_un_texto_no_puede_romper_la_pagina(self):
        ubicacion = 'Madrid </script><script>alert("hola")</script> & más'
        gd.generar_dashboard(self.csv, self.html, ubicacion)
        html = self.html.read_text(encoding="utf-8")
        self.assertNotIn("<script>alert", html)
        self.assertEqual(datos_del_html(html)["ubicacion"], ubicacion)

    def test_la_plantilla_no_tiene_datos(self):
        plantilla = gd.PLANTILLA.read_text(encoding="utf-8")
        self.assertEqual(plantilla.count(gd.MARCADOR), 1)
        self.assertNotIn("2026-10-13", plantilla)
        etiqueta = re.search(r'<script src="https://cdn\.jsdelivr\.net/npm/echarts@[^"]+"[^>]*>', plantilla).group(0)
        self.assertIn('integrity="sha384-', etiqueta)
        self.assertIn('crossorigin="anonymous"', etiqueta)

    def test_linea_de_comandos(self):
        salida, errores = io.StringIO(), io.StringIO()
        with redirect_stdout(salida), redirect_stderr(errores):
            ok = gd.main(["--csv", str(self.csv), "--salida", str(self.html)])
            falla = gd.main(["--csv", str(self.dir / "no_existe.csv"), "--salida", str(self.html)])
        self.assertEqual((ok, falla), (0, 1))
        self.assertIn("7 días, del 13/10/2026 al 19/10/2026", salida.getvalue())
        self.assertIn("No existe el fichero", errores.getvalue())


if __name__ == "__main__":
    unittest.main()
