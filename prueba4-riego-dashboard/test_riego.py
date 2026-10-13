"""Pruebas de la fórmula, del CSV y de la generación del dashboard.

Ejecutar desde la carpeta del proyecto con:
    python -m unittest -v

No necesitan internet: la API se sustituye por una respuesta real ya guardada.
"""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import generar_dashboard
import obtener_datos
from obtener_datos import calcular_uso_riego

# Respuesta real de Open-Meteo para Madrid, consultada el 12/10/2026 (resumida).
RESPUESTA_GEOCODIFICACION = {
    "results": [{
        "name": "Madrid", "latitude": 40.4165, "longitude": -3.70256,
        "country": "España", "admin1": "Comunidad Autónoma de Madrid",
    }],
}
RESPUESTA_PREVISION = {
    "timezone": "Europe/Madrid",
    "daily_units": {"time": "iso8601", "precipitation_sum": "mm"},
    "daily": {
        "time": ["2026-10-12", "2026-10-13", "2026-10-14", "2026-10-15",
                 "2026-10-16", "2026-10-17", "2026-10-18"],
        "precipitation_sum": [0.00, 0.00, 0.00, 0.00, 0.00, 4.05, 15.90],
    },
}


def respuesta_http(datos: dict) -> io.BytesIO:
    """Imita lo que devuelve urllib.request.urlopen()."""
    return io.BytesIO(json.dumps(datos).encode("utf-8"))


class PruebasFormula(unittest.TestCase):
    def test_sin_precipitacion_el_uso_es_maximo(self):
        self.assertEqual(calcular_uso_riego(0), 50)

    def test_valores_intermedios(self):
        self.assertEqual(calcular_uso_riego(2.3), 27)
        # Sin redondear, (5 - 4.05) * 10 daría 9.500000000000002
        self.assertEqual(calcular_uso_riego(4.05), 9.5)

    def test_justo_en_el_umbral_el_uso_es_cero(self):
        self.assertEqual(calcular_uso_riego(5), 0)

    def test_por_encima_del_umbral_el_uso_es_cero(self):
        self.assertEqual(calcular_uso_riego(5.1), 0)
        self.assertEqual(calcular_uso_riego(15.9), 0)

    def test_una_precipitacion_negativa_es_un_error(self):
        with self.assertRaises(ValueError):
            calcular_uso_riego(-1)


class PruebasApi(unittest.TestCase):
    def test_lee_la_precipitacion_de_la_respuesta(self):
        with mock.patch("urllib.request.urlopen", return_value=respuesta_http(RESPUESTA_PREVISION)) as urlopen:
            datos = obtener_datos.obtener_precipitacion(40.4165, -3.70256, dias=7)
        self.assertEqual(len(datos), 7)
        self.assertEqual(datos[5], ("2026-10-17", 4.05))
        url = urlopen.call_args[0][0].full_url
        self.assertIn("daily=precipitation_sum", url)
        self.assertIn("forecast_days=7", url)

    def test_un_dia_sin_dato_no_se_convierte_en_cero(self):
        incompleta = json.loads(json.dumps(RESPUESTA_PREVISION))
        incompleta["daily"]["precipitation_sum"][3] = None
        with mock.patch("urllib.request.urlopen", return_value=respuesta_http(incompleta)):
            with self.assertRaises(obtener_datos.ErrorDatos):
                obtener_datos.obtener_precipitacion(40.4, -3.7)

    def test_localidad_inexistente(self):
        with mock.patch("urllib.request.urlopen", return_value=respuesta_http({"generationtime_ms": 0.2})):
            with self.assertRaises(obtener_datos.ErrorDatos):
                obtener_datos.buscar_localidad("Xyzzyqqqzz")


class PruebasCsv(unittest.TestCase):
    def setUp(self):
        carpeta = tempfile.TemporaryDirectory()
        self.addCleanup(carpeta.cleanup)
        self.ruta = Path(carpeta.name) / "riego.csv"

    def test_columnas_y_formato_del_csv(self):
        filas = obtener_datos.calcular_filas([("2026-10-17", 4.05), ("2026-10-18", 15.9)])
        obtener_datos.guardar_csv(filas, self.ruta)
        lineas = self.ruta.read_text(encoding="utf-8-sig").splitlines()
        self.assertEqual(lineas, [
            "Día,Precipitación (mm),Uso estimado de riego",
            "2026-10-17,4.05,9.50",
            "2026-10-18,15.90,0.00",
        ])

    def test_el_generador_lee_el_csv_que_escribe_obtener_datos(self):
        obtener_datos.guardar_csv([("2026-10-17", 4.05, 9.5)], self.ruta)
        self.assertEqual(generar_dashboard.leer_csv(self.ruta),
                         [{"dia": "2026-10-17", "precipitacion": 4.05, "uso": 9.5}])

    def test_admite_un_csv_guardado_desde_excel_en_espanol(self):
        # Excel en español usa ";" como separador, "," decimal, fechas dd/mm/aaaa y Windows-1252.
        texto = "Día;Precipitación (mm);Uso estimado de riego\r\n17/10/2026;4,05;9,5\r\n;;\r\n"
        self.ruta.write_bytes(texto.encode("cp1252"))
        filas = generar_dashboard.leer_csv(self.ruta)
        self.assertEqual(filas, [{"dia": "17/10/2026", "precipitacion": 4.05, "uso": 9.5}])
        self.assertEqual(generar_dashboard.etiqueta_dia(filas[0]["dia"]), "sáb 17 oct")

    def test_avisa_si_falta_una_columna(self):
        self.ruta.write_text("Día,Lluvia\n2026-10-12,0\n", encoding="utf-8")
        with self.assertRaisesRegex(generar_dashboard.ErrorCSV, "Precipitación"):
            generar_dashboard.leer_csv(self.ruta)

    def test_avisa_si_un_valor_no_es_un_numero(self):
        self.ruta.write_text("Día,Precipitación (mm),Uso estimado de riego\n"
                             "2026-10-12,mucha,50\n", encoding="utf-8")
        with self.assertRaisesRegex(generar_dashboard.ErrorCSV, "línea 2"):
            generar_dashboard.leer_csv(self.ruta)


class PruebasDashboard(unittest.TestCase):
    def setUp(self):
        carpeta = tempfile.TemporaryDirectory()
        self.addCleanup(carpeta.cleanup)
        self.carpeta = Path(carpeta.name)

    def test_etiquetas_de_los_dias(self):
        self.assertEqual(generar_dashboard.etiqueta_dia("2026-10-12"), "lun 12 oct")
        self.assertEqual(generar_dashboard.etiqueta_dia("Día 1"), "Día 1")  # no es fecha: se deja igual

    def test_un_texto_del_csv_no_puede_cerrar_la_etiqueta_script(self):
        html = generar_dashboard.generar_html({"dias": ["</script><b>hola</b>"]}, "const DATOS = __DATOS_JSON__;")
        self.assertNotIn("</script>", html)

    def test_flujo_completo_y_regeneracion_al_cambiar_el_csv(self):
        csv_ruta, html_ruta = self.carpeta / "riego.csv", self.carpeta / "dashboard.html"
        respuestas = [respuesta_http(RESPUESTA_GEOCODIFICACION), respuesta_http(RESPUESTA_PREVISION)]
        with mock.patch("urllib.request.urlopen", side_effect=respuestas), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(obtener_datos.main(["--ciudad", "Madrid", "--salida", str(csv_ruta)]), 0)
            self.assertEqual(generar_dashboard.main(["--csv", str(csv_ruta), "--salida", str(html_ruta)]), 0)
        html = html_ruta.read_text(encoding="utf-8")
        self.assertNotIn(generar_dashboard.MARCADOR, html)
        self.assertIn('"sáb 17 oct"', html)
        self.assertIn("4.05", html)

        # Se cambia un valor del CSV y se vuelve a ejecutar el generador: el HTML cambia.
        csv_ruta.write_text(csv_ruta.read_text(encoding="utf-8-sig").replace("4.05,9.50", "12.30,0.00"),
                            encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()):
            generar_dashboard.main(["--csv", str(csv_ruta), "--salida", str(html_ruta)])
        html = html_ruta.read_text(encoding="utf-8")
        self.assertIn("12.3", html)
        self.assertNotIn("4.05", html)


if __name__ == "__main__":
    unittest.main()
