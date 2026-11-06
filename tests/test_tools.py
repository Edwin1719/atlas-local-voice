"""Pruebas de la herramienta de búsqueda, sin red."""
from __future__ import annotations

import asyncio
import unittest
from unittest import mock

from atlas.tools import (
    GOOGLE_NEWS_SEARCH,
    GOOGLE_NEWS_TOP,
    TOOLS,
    _edicion,
    _es_generica,
    _hace,
    _url_real,
    buscar_web,
    es_consulta_de_noticias,
    execute,
    parse_news,
    parse_results,
)

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

NEWS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <item>
    <title>Dólar hoy en Colombia: así arranca el precio | El Espectador - El Espectador</title>
    <pubDate>Fri, 06 Nov 2026 13:45:00 GMT</pubDate>
    <source url="https://www.elespectador.com">El Espectador</source>
  </item>
  <item>
    <title>Convocan a paro nacional en Colombia | Últimas Noticias</title>
    <pubDate>Fri, 06 Nov 2026 13:16:42 GMT</pubDate>
    <source url="https://ultimasnoticias.com.ve">Últimas Noticias</source>
  </item>
  <item>
    <title>Fiscalía confirma imputación - Revista Semana</title>
    <pubDate>Fri, 06 Nov 2026 12:00:00 GMT</pubDate>
    <source url="https://www.semana.com">Revista Semana</source>
  </item>
  <item>
    <title>Cuarto titular sin fuente</title>
  </item>
</channel></rss>
"""


class TestEnrutadoDeNoticias(unittest.TestCase):

    def test_reconoce_consulta_de_noticias(self):
        self.assertTrue(es_consulta_de_noticias("últimas noticias de Colombia"))
        self.assertTrue(es_consulta_de_noticias("titulares de hoy"))
        self.assertFalse(es_consulta_de_noticias("precio del dólar"))

    def test_distingue_peticion_generica_de_tema(self):
        self.assertTrue(_es_generica("últimas noticias de Colombia para hoy"))
        self.assertTrue(_es_generica("noticias"))
        self.assertFalse(_es_generica("noticias del paro nacional"))
        self.assertFalse(_es_generica("noticias de la selección"))

    def test_edicion_por_pais(self):
        self.assertEqual(_edicion("noticias de Colombia")[0], ("es-CO", "CO", "CO:es-419"))
        self.assertEqual(_edicion("noticias de México")[0], ("es-419", "MX", "MX:es-419"))


class TestTitulares(unittest.TestCase):

    def test_parsea_titulos_fuente_y_fecha(self):
        noticias = parse_news(NEWS_XML)
        self.assertEqual(len(noticias), 4)
        self.assertEqual(noticias[0]["titulo"], "Dólar hoy en Colombia: así arranca el precio")
        self.assertEqual(noticias[0]["fuente"], "El Espectador")
        self.assertEqual(noticias[1]["titulo"], "Convocan a paro nacional en Colombia")
        self.assertEqual(noticias[2]["titulo"], "Fiscalía confirma imputación")
        self.assertEqual(noticias[3]["fuente"], "")

    def test_xml_invalido_no_rompe(self):
        self.assertEqual(parse_news("<html>no es rss</html>"), [])

    def test_hace_relativo(self):
        self.assertEqual(_hace(""), "")
        self.assertEqual(_hace("no es fecha"), "")
        self.assertIn("días", _hace("Fri, 06 Nov 2020 13:45:00 GMT"))


class RespuestaNoticias:
    status_code = 200
    text = NEWS_XML


class ClienteNoticias:
    instancias = []

    def __init__(self, *a, **k):
        self.llamadas = []
        ClienteNoticias.instancias.append(self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, params=None, headers=None):
        self.llamadas.append((url, dict(params or {})))
        return RespuestaNoticias()


class TestBusquedaDeNoticias(unittest.TestCase):

    def setUp(self):
        ClienteNoticias.instancias.clear()

    def test_portada_para_peticion_generica(self):
        with mock.patch("atlas.tools.httpx.AsyncClient", ClienteNoticias):
            salida = asyncio.run(buscar_web("últimas noticias de Colombia para hoy"))
        llamada = ClienteNoticias.instancias[0].llamadas[0]
        self.assertEqual(llamada[0], GOOGLE_NEWS_TOP)
        self.assertEqual(llamada[1]["ceid"], "CO:es-419")
        self.assertIn("El Espectador", salida)
        self.assertIn("Titulares recientes", salida)
        self.assertNotIn("https://", salida)

    def test_busqueda_con_fecha_para_tema_concreto(self):
        with mock.patch("atlas.tools.httpx.AsyncClient", ClienteNoticias):
            asyncio.run(buscar_web("noticias del paro nacional"))
        llamada = ClienteNoticias.instancias[0].llamadas[0]
        self.assertEqual(llamada[0], GOOGLE_NEWS_SEARCH)
        self.assertIn("when:1d", llamada[1]["q"])
        self.assertIn("paro nacional", llamada[1]["q"])

    def test_consulta_con_solo_pais_va_a_noticias(self):
        with mock.patch("atlas.tools.httpx.AsyncClient", ClienteNoticias):
            asyncio.run(buscar_web("Colombia hoy"))
        self.assertEqual(ClienteNoticias.instancias[0].llamadas[0][0], GOOGLE_NEWS_TOP)

    def test_tres_titulares_como_maximo(self):
        with mock.patch("atlas.tools.httpx.AsyncClient", ClienteNoticias):
            salida = asyncio.run(buscar_web("noticias de Colombia"))
        self.assertEqual(len(salida.splitlines()), 4)  # cabecera + 3
        self.assertNotIn("Cuarto titular", salida)


if __name__ == "__main__":
    unittest.main()
