"""Pruebas de la herramienta de búsqueda, sin red."""
from __future__ import annotations

import asyncio
import unittest
from unittest import mock

from atlas.tools import TOOLS, _url_real, execute, parse_results

HTML = """
<div class="result">
  <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fnasa.gov%2F&amp;rut=x">NASA &amp; ciencia</a>
  <a class="result__snippet" href="//x">Ultimas <b>noticias</b> de la NASA.</a>
</div>
<div class="result">
  <a class="result__a" href="https://ejemplo.com/dos">Segundo resultado</a>
  <a class="result__snippet" href="//y">Otro resumen.</a>
</div>
"""


class TestEsquema(unittest.TestCase):

    def test_una_sola_herramienta(self):
        self.assertEqual(len(TOOLS), 1)
        funcion = TOOLS[0]["function"]
        self.assertEqual(funcion["name"], "buscar_web")
        self.assertEqual(funcion["parameters"]["required"], ["consulta"])


class TestParseo(unittest.TestCase):

    def test_extrae_titulo_resumen_y_url(self):
        resultados = parse_results(HTML)
        self.assertEqual(len(resultados), 2)
        self.assertEqual(resultados[0]["titulo"], "NASA & ciencia")
        self.assertEqual(resultados[0]["url"], "https://nasa.gov/")
        self.assertIn("noticias", resultados[0]["resumen"])
        self.assertNotIn("<b>", resultados[0]["resumen"])

    def test_segunda_url_sin_envoltorio(self):
        self.assertEqual(parse_results(HTML)[1]["url"], "https://ejemplo.com/dos")

    def test_respeta_el_limite(self):
        self.assertEqual(len(parse_results(HTML, limite=1)), 1)

    def test_html_sin_resultados(self):
        self.assertEqual(parse_results("<html>nada</html>"), [])

    def test_decodifica_el_redirect(self):
        self.assertEqual(
            _url_real("//duckduckgo.com/l/?uddg=https%3A%2F%2Fa.com%2Fb&amp;rut=z"),
            "https://a.com/b",
        )


class TestEjecucion(unittest.TestCase):

    def test_herramienta_desconocida(self):
        salida = asyncio.run(execute("no_existe", {}))
        self.assertIn("desconocida", salida)

    def test_consulta_vacia(self):
        salida = asyncio.run(execute("buscar_web", {"consulta": "  "}))
        self.assertIn("No se indicó", salida)

    def test_fallo_de_red_devuelve_texto(self):
        class ClienteRoto:
            def __init__(self, *a, **k):
                pass
            async def __aenter__(self):
                return self
            async def __aexit__(self, *a):
                return False
            async def get(self, *a, **k):
                raise RuntimeError("sin red")

        with mock.patch("atlas.tools.httpx.AsyncClient", ClienteRoto):
            salida = asyncio.run(execute("buscar_web", {"consulta": "algo"}))
        self.assertIn("No se pudo consultar internet", salida)

    def test_bloqueo_202_da_mensaje_claro_sin_reintentar(self):
        """DuckDuckGo responde 202/429 cuando limita; debe reintentar y avisar."""
        intentos = {"n": 0}

        class RespuestaLimitada:
            status_code = 202
            text = ""

        class ClienteLimitado:
            def __init__(self, *a, **k):
                pass
            async def __aenter__(self):
                return self
            async def __aexit__(self, *a):
                return False
            async def get(self, *a, **k):
                intentos["n"] += 1
                return RespuestaLimitada()

        with mock.patch("atlas.tools.httpx.AsyncClient", ClienteLimitado):
            with mock.patch("atlas.tools.asyncio.sleep", mock.AsyncMock()):
                salida = asyncio.run(execute("buscar_web", {"consulta": "python"}))

        self.assertEqual(intentos["n"], 1)  # un 202 no se reintenta: es bloqueo
        self.assertIn("no está disponible", salida)
        self.assertNotIn("202", salida)
    def test_limite_429_reintenta_una_vez(self):
        intentos = {"n": 0}

        class Respuesta429:
            status_code = 429
            text = ""

        class Cliente429:
            def __init__(self, *a, **k):
                pass
            async def __aenter__(self):
                return self
            async def __aexit__(self, *a):
                return False
            async def get(self, *a, **k):
                intentos["n"] += 1
                return Respuesta429()

        with mock.patch("atlas.tools.httpx.AsyncClient", Cliente429):
            with mock.patch("atlas.tools.asyncio.sleep", mock.AsyncMock()):
                salida = asyncio.run(execute("buscar_web", {"consulta": "python"}))

        self.assertEqual(intentos["n"], 2)
        self.assertIn("no está disponible", salida)

if __name__ == "__main__":
    unittest.main()
