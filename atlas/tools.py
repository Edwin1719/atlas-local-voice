"""Herramientas que el modelo puede invocar.

Una sola herramienta, a propósito: añadir más degrada la selección en un modelo
de 1,73 B. Por dentro enruta a dos fuentes:

- Noticias: Google News RSS (titulares reales, con medio y hora).
- Resto: DuckDuckGo HTML, sin clave de API.

Por qué no DuckDuckGo para noticias: al preguntar «últimas noticias de Colombia»
devolvía las portadas de los medios («consulta EL TIEMPO»), y el asistente
repetía esa recomendación en vez de contar las noticias del día.

El esquema va en inglés porque así lo entrenaron. La descripción del argumento pide
términos de búsqueda cortos: medido, si no se le indica, manda la pregunta entera.
"""
from __future__ import annotations

import asyncio
import re
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape

import httpx

ENDPOINT = "https://html.duckduckgo.com/html/"
GOOGLE_NEWS_TOP = "https://news.google.com/rss"
GOOGLE_NEWS_SEARCH = "https://news.google.com/rss/search"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
CABECERAS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml",
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
}
# 202 es el bloqueo blando de DuckDuckGo (reintentar no ayuda en segundos);
# 429 es un límite temporal, donde sí vale un reintento.
ESTADOS_LIMITE = (202, 429)
TIMEOUT_S = 8.0
MAX_RESULTADOS = 4
# Para noticias, tres titulares: la voz no debe leer un periódico entero.
MAX_NOTICIAS = 3

# Ediciones de Google News: (hl, gl, ceid). Por defecto, Colombia, donde nació
# el proyecto; añadir otra entrada para cambiar de país.
EDICIONES = {
    "colombia": ("es-CO", "CO", "CO:es-419"),
    "méxico": ("es-419", "MX", "MX:es-419"),
    "mexico": ("es-419", "MX", "MX:es-419"),
    "argentina": ("es-419", "AR", "AR:es-419"),
    "chile": ("es-419", "CL", "CL:es-419"),
    "perú": ("es-419", "PE", "PE:es-419"),
    "peru": ("es-419", "PE", "PE:es-419"),
    "ecuador": ("es-419", "EC", "EC:es-419"),
    "venezuela": ("es-419", "VE", "VE:es-419"),
    "bolivia": ("es-419", "BO", "BO:es-419"),
    "uruguay": ("es-419", "UY", "UY:es-419"),
    "paraguay": ("es-419", "PY", "PY:es-419"),
    "españa": ("es", "ES", "ES:es"),
    "espana": ("es", "ES", "ES:es"),
    "estados unidos": ("es-419", "US", "US:es-419"),
}
EDICION_POR_DEFECTO = EDICIONES["colombia"]

# Cualquier palabra de estas basta para tratar la consulta como noticias.
NOTICIAS = re.compile(
    r"\b(noticias?|última hora|ultima hora|titulares|headlines?|news|"
    r"actualidad|acontecer)\b",
    re.IGNORECASE,
)

# Relleno que no identifica un tema. Al quitarlo, «últimas noticias de Colombia
# para hoy» queda en «colombia»: es una petición genérica, no un tema concreto.
_RELLENO = re.compile(
    r"\b(las|los|la|el|de|del|para|en|hoy|día|dia|días|dias|últimas|ultimas|"
    r"última|ultima|principales|noticias?|titulares|headlines?|news|actualidad|"
    r"acontecer|hora|sobre|un|una|unos|unas|y|e|o|qué|que|cuales|cuáles)\b",
    re.IGNORECASE,
)

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "buscar_web",
            "description": "Busca información actual en internet. Para noticias "
            "devuelve titulares recientes con el medio y la hora. Úsala SIEMPRE "
            "que pregunten por noticias, precios, clima, resultados deportivos o "
            "cualquier hecho reciente que no puedas saber con certeza.",
            "parameters": {
                "type": "object",
                "properties": {
                    "consulta": {
                        "type": "string",
                        "description": "Términos de búsqueda cortos, no la pregunta completa",
                    }
                },
                "required": ["consulta"],
            },
        },
    }
]

_RESULTADO = re.compile(
    r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.DOTALL
)
_SNIPPET = re.compile(r'class="result__snippet"[^>]*>(.*?)</a>', re.DOTALL)
_ETIQUETAS = re.compile(r"<[^>]+>")


def _texto(fragmento: str) -> str:
    sin_etiquetas = _ETIQUETAS.sub("", fragmento)
    return re.sub(r"\s+", " ", unescape(sin_etiquetas)).strip()


def _url_real(url: str) -> str:
    """DuckDuckGo envuelve los enlaces; se extrae el destino real."""
    if "uddg=" in url:
        consulta = urllib.parse.urlparse(url).query
        destino = urllib.parse.parse_qs(consulta).get("uddg", [""])[0]
        if destino:
            return destino
    return "https:" + url if url.startswith("//") else url


def parse_results(html: str, limite: int = MAX_RESULTADOS) -> list[dict]:
    """Extrae título, resumen y URL de la página de resultados."""
    marcas = list(_RESULTADO.finditer(html))
    resumenes = list(_SNIPPET.finditer(html))
    resultados: list[dict] = []
    for indice, marca in enumerate(marcas[:limite]):
        resumen = ""
        siguiente = marcas[indice + 1].start() if indice + 1 < len(marcas) else len(html)
        for candidato in resumenes:
            if marca.end() <= candidato.start() < siguiente:
                resumen = _texto(candidato.group(1))
                break
        resultados.append(
            {
                "titulo": _texto(marca.group(2)),
                "url": _url_real(marca.group(1)),
                "resumen": resumen,
            }
        )
    return resultados


def es_consulta_de_noticias(consulta: str) -> bool:
    """True si la consulta pide noticias y debe ir a Google News, no a DuckDuckGo."""
    return bool(NOTICIAS.search(consulta or ""))


def _tema(consulta: str) -> str:
    resto = _RELLENO.sub(" ", consulta or "")
    resto = re.sub(r"[^\w\sáéíóúüñÁÉÍÓÚÜÑ]", " ", resto)
    return re.sub(r"\s+", " ", resto).strip().lower()


def _edicion(consulta: str) -> tuple[tuple[str, str, str], str]:
    """Devuelve (edición de Google News, tema restante sin el país)."""
    tema = _tema(consulta)
    for nombre, edicion in EDICIONES.items():
        patron = r"\b" + re.escape(nombre) + r"\b"
        if re.search(patron, tema):
            resto = re.sub(patron, " ", tema)
            return edicion, re.sub(r"\s+", " ", resto).strip()
    return EDICION_POR_DEFECTO, tema


def _es_generica(consulta: str) -> bool:
    """«Últimas noticias de Colombia» no tiene tema: es la portada del día."""
    _edicion_ignorada, resto = _edicion(consulta)
    return resto == ""


def parse_news(xml_text: str, limite: int = MAX_RESULTADOS) -> list[dict]:
    """Extrae titulares del RSS de Google News (o de cualquier RSS con source)."""
    try:
        raiz = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    noticias: list[dict] = []
    for item in raiz.iter("item"):
        titulo = (item.findtext("title") or "").strip()
        if not titulo:
            continue
        fuente = ""
        for hijo in item:
            # Google usa <source>; Bing, un <Source> con espacio de nombres.
            if hijo.tag.split("}")[-1].lower() == "source":
                fuente = (hijo.text or "").strip()
                break
        fecha = (item.findtext("pubDate") or "").strip()
        if fuente:
            # Google añade el medio al final con " - ", " | " o un guion largo,
            # a veces dos veces («… | El Colombiano - El Colombiano»).
            limpio = True
            while limpio:
                limpio = False
                for separador in (" - ", " | ", " — ", " – "):
                    sufijo = separador + fuente
                    if titulo.endswith(sufijo):
                        titulo = titulo[: -len(sufijo)].strip()
                        limpio = True
                        break
        noticias.append({"titulo": titulo, "fuente": fuente, "fecha": fecha})
        if len(noticias) >= limite:
            break
    return noticias


def _hace(fecha: str) -> str:
    """Convierte una fecha RFC 822 en «hace 12 min», «hace 3 h» o «ayer»."""
    try:
        cuando = parsedate_to_datetime(fecha)
    except (TypeError, ValueError):
        return ""
    if cuando is None:
        return ""
    if cuando.tzinfo is None:
        cuando = cuando.replace(tzinfo=timezone.utc)
    minutos = int(max(0.0, (datetime.now(timezone.utc) - cuando).total_seconds()) // 60)
    if minutos < 60:
        return "hace {} min".format(max(1, minutos))
    horas = minutos // 60
    if horas < 24:
        return "hace {} h".format(horas)
    dias = horas // 24
    if dias == 1:
        return "ayer"
    return "hace {} días".format(dias)


def _formato_noticias(consulta: str, noticias: list[dict]) -> str:
    lineas = ["Titulares recientes sobre «{}»:".format(consulta)]
    for posicion, noticia in enumerate(noticias, 1):
        fuente = noticia["fuente"] or "medio sin identificar"
        cuando = _hace(noticia["fecha"])
        detalle = "{}, {}".format(fuente, cuando) if cuando else fuente
        # Sin URL: la voz no debe leer direcciones y el modelo ya tiene el medio.
        lineas.append("{}. {} ({})".format(posicion, noticia["titulo"], detalle))
    return "\n".join(lineas)


async def _buscar_noticias(consulta: str, limite: int) -> str:
    """Titulares reales de Google News; portada del día si no hay tema concreto."""
    limite = min(limite, MAX_NOTICIAS)
    hl, gl, ceid = _edicion(consulta)[0]
    base = {"hl": hl, "gl": gl, "ceid": ceid}
    noticias: list[dict] = []
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_S, follow_redirects=True) as cliente:
            if _es_generica(consulta):
                respuesta = await cliente.get(
                    GOOGLE_NEWS_TOP, params=base, headers=CABECERAS
                )
                if respuesta.status_code == 200:
                    noticias = parse_news(respuesta.text, limite)
            if not noticias:
                respuesta = await cliente.get(
                    GOOGLE_NEWS_SEARCH,
                    params=dict(base, q=consulta + " when:1d"),
                    headers=CABECERAS,
                )
                if respuesta.status_code == 200:
                    noticias = parse_news(respuesta.text, limite)
            if not noticias:
                # Sin filtro temporal: algunas consultas no tienen nada del día.
                respuesta = await cliente.get(
                    GOOGLE_NEWS_SEARCH,
                    params=dict(base, q=consulta),
                    headers=CABECERAS,
                )
                if respuesta.status_code == 200:
                    noticias = parse_news(respuesta.text, limite)
    except Exception as exc:  # una herramienta nunca debe tumbar el turno
        return "No se pudieron obtener las noticias: {}".format(exc)
    if not noticias:
        return "No se encontraron titulares recientes sobre «{}».".format(consulta)
    return _formato_noticias(consulta, noticias)


async def buscar_web(consulta: str, limite: int = MAX_RESULTADOS) -> str:
    """Devuelve los resultados como texto plano para el modelo."""
    termino = (consulta or "").strip()
    if not termino:
        return "No se indicó qué buscar."

    # Las noticias van a Google News: DuckDuckGo devolvía portadas de medios.
    # Una consulta que solo nombra el país («Colombia hoy») también es una
    # petición de portada: el modelo abrevia así las preguntas de actualidad.
    if es_consulta_de_noticias(termino) or _es_generica(termino):
        return await _buscar_noticias(termino, limite)

    respuesta = None
    for intento in range(2):
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT_S, follow_redirects=True) as cliente:
                respuesta = await cliente.get(ENDPOINT, params={"q": termino}, headers=CABECERAS)
        except Exception as exc:  # una herramienta nunca debe tumbar el turno
            return "No se pudo consultar internet: {}".format(exc)
        if respuesta.status_code == 200:
            break
        if respuesta.status_code not in ESTADOS_LIMITE:
            return "La búsqueda devolvió el estado {}.".format(respuesta.status_code)
        if respuesta.status_code == 429 and intento == 0:
            await asyncio.sleep(1.5)
            continue
        break  # un 202 no mejora reintentando: se corta aquí
    if respuesta.status_code in ESTADOS_LIMITE:
        return (
            "La búsqueda no está disponible ahora mismo: el servicio gratuito ha "
            "limitado las peticiones. Inténtalo de nuevo en unos minutos."
        )
    resultados = parse_results(respuesta.text, limite)
    if not resultados:
        return "La búsqueda no devolvió resultados para «{}».".format(termino)
    lineas = ["Resultados de búsqueda para «{}»:".format(termino)]
    for posicion, item in enumerate(resultados, 1):
        lineas.append(
            "{}. {} — {} ({})".format(
                posicion, item["titulo"], item["resumen"][:200], item["url"]
            )
        )
    return "\n".join(lineas)


async def execute(nombre: str, argumentos: dict | None) -> str:
    """Ejecuta una herramienta. Su salida es dato, nunca instrucción."""
    if nombre == "buscar_web":
        return await buscar_web(str((argumentos or {}).get("consulta", "")))
    return "Herramienta desconocida: {}".format(nombre)
