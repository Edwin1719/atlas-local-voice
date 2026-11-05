"""Herramientas que el modelo puede invocar.

Una sola, a propósito. Buscar en internet es lo que más amplía un asistente de voz,
y añadir herramientas de más degrada la selección en un modelo de 1,73 B.

El esquema va en inglés porque así lo entrenaron. La descripción del argumento pide
términos de búsqueda cortos: medido, si no se le indica, manda la pregunta entera.
"""
from __future__ import annotations

import asyncio
import re
import urllib.parse
from html import unescape

import httpx

ENDPOINT = "https://html.duckduckgo.com/html/"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
CABECERAS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
}
# 202 es el bloqueo blando de DuckDuckGo (reintentar no ayuda en segundos);
# 429 es un límite temporal, donde sí vale un reintento.
ESTADOS_LIMITE = (202, 429)
TIMEOUT_S = 8.0
MAX_RESULTADOS = 4

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "buscar_web",
            "description": "Busca información actual en internet. Úsala SIEMPRE que "
            "pregunten por noticias, precios, clima, resultados deportivos o "
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


async def buscar_web(consulta: str, limite: int = MAX_RESULTADOS) -> str:
    """Devuelve los resultados como texto plano para el modelo."""
    termino = (consulta or "").strip()
    if not termino:
        return "No se indicó qué buscar."
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
