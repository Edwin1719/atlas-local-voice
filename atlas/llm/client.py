"""Cliente asíncrono de Ollama para las tres etapas del asistente.

Endpoints usados (verificados contra Ollama 0.40.14 con lfm3-omni:2b):

  ASR  POST /v1/chat/completions  con content-part input_audio  (base64 + WAV)
  LLM  POST /api/chat             con stream=True (NDJSON)
  TTS  POST /v1/audio/speech      devuelve WAV 24 kHz mono 16 bits

Aviso: /api/chat acepta el campo audio pero lo IGNORA en silencio. El audio
solo entra por la ruta compatible con OpenAI.
"""
from __future__ import annotations

import base64
import json
from typing import AsyncIterator, Sequence

import httpx

from atlas.core.audio_utils import pcm16_to_wav
from atlas.core.config import Settings

TRANSCRIBE_INSTRUCTION = (
    "Transcribe literalmente el audio en español. "
    "Devuelve únicamente la transcripción, sin comillas, sin comentarios "
    "y sin describir el sonido. Si no hay voz inteligible, devuelve vacío."
)


class OllamaError(RuntimeError):
    """Fallo al comunicarse con Ollama o respuesta inesperada del servidor."""


class VoiceClient:
    """Envoltorio mínimo sobre la API HTTP de Ollama."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._http = httpx.AsyncClient(
            base_url=settings.base_url.rstrip("/"),
            timeout=settings.request_timeout_s,
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    # ------------------------------------------------------------- modelos

    async def list_models(self) -> list[str]:
        """Nombres de los modelos instalados. Lanza OllamaError si no hay servidor."""
        try:
            response = await self._http.get("/api/tags")
        except httpx.HTTPError as exc:
            raise OllamaError(
                "No se pudo conectar con Ollama en {}.".format(self._settings.base_url)
                + " ¿Está el servicio en marcha? Prueba: ollama list"
            ) from exc
        if response.status_code != 200:
            raise OllamaError(
                "Ollama respondió {} al listar modelos: {}".format(
                    response.status_code, response.text[:200]
                )
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise OllamaError("Respuesta no válida de /api/tags") from exc
        return [item.get("name", "") for item in payload.get("models", [])]

    async def ensure_model(self) -> None:
        """Verifica que el modelo configurado exista, con mensaje accionable."""
        models = await self.list_models()
        wanted = self._settings.model
        if wanted in models:
            return
        base = wanted.split(":")[0]
        available = ", ".join(sorted(m for m in models if m)) or "(ninguno)"
        raise OllamaError(
            "El modelo '{}' no está instalado. Disponibles: {}. ".format(wanted, available)
            + "Cambia VA_MODEL o ejecuta: ollama pull {}".format(base)
        )

    # ---------------------------------------------------------------- ASR

    async def transcribe(self, pcm: bytes) -> str:
        """PCM16 a texto usando el modelo multimodal como reconocedor."""
        wav = pcm16_to_wav(pcm, self._settings.sample_rate, self._settings.channels)
        encoded = base64.b64encode(wav).decode("ascii")
        payload = {
            "model": self._settings.model,
            "stream": False,
            "temperature": 0.0,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": TRANSCRIBE_INSTRUCTION},
                        {
                            "type": "input_audio",
                            "input_audio": {"data": encoded, "format": "wav"},
                        },
                    ],
                }
            ],
        }
        try:
            response = await self._http.post("/v1/chat/completions", json=payload)
        except httpx.HTTPError as exc:
            raise OllamaError("Fallo de red al transcribir: {}".format(exc)) from exc
        if response.status_code != 200:
            raise OllamaError(
                "Transcripción rechazada ({}): {}".format(
                    response.status_code, response.text[:300]
                )
            )
        try:
            data = response.json()
            content = data["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError) as exc:
            raise OllamaError("Respuesta de transcripción con formato inesperado") from exc
        return _clean_transcript(content)

    # ---------------------------------------------------------------- LLM

    async def stream_events(
        self,
        messages: Sequence[dict],
        tools: Sequence[dict] | None = None,
        options: dict | None = None,
    ) -> AsyncIterator[dict]:
        """Emite eventos del chat: {"type": "token"} o {"type": "tool_calls"}.

        En streaming, Ollama manda los tool_calls completos en el primer fragmento y
        con el contenido vacío, así que se puede decidir antes de emitir texto.
        """
        payload = {
            "model": self._settings.model,
            "stream": True,
            "options": {"temperature": self._settings.temperature, **(options or {})},
            "messages": list(messages),
        }
        if tools:
            payload["tools"] = list(tools)
        try:
            async with self._http.stream("POST", "/api/chat", json=payload) as response:
                if response.status_code != 200:
                    await response.aread()
                    raise OllamaError("Chat rechazado ({})".format(response.status_code))
                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        chunk = json.loads(line)
                    except ValueError:
                        continue
                    error = chunk.get("error")
                    if error:
                        raise OllamaError("Ollama devolvió un error: {}".format(error))
                    message = chunk.get("message") or {}
                    llamadas = message.get("tool_calls")
                    if llamadas:
                        yield {"type": "tool_calls", "calls": llamadas}
                    token = message.get("content") or ""
                    if token:
                        yield {"type": "token", "text": token}
        except httpx.HTTPError as exc:
            raise OllamaError("Fallo de red en el chat: {}".format(exc)) from exc

    async def stream_chat(self, messages: Sequence[dict]) -> AsyncIterator[str]:
        """Solo el texto de la respuesta, sin herramientas."""
        async for evento in self.stream_events(messages):
            if evento["type"] == "token":
                yield evento["text"]

    # ---------------------------------------------------------------- TTS

    async def synthesize(self, text: str) -> bytes:
        """Texto a WAV (24 kHz, mono, 16 bits)."""
        clean = text.strip()
        if not clean:
            return b""
        payload = {
            "model": self._settings.model,
            "input": clean,
            "voice": self._settings.voice,
            "response_format": "wav",
        }
        # Ollama sirve el audio en chunked y a veces cierra la conexión sin el
        # terminador, lo que hace fallar la lectura completa de httpx. Se lee de
        # forma tolerante y se conserva lo recibido.
        buffer = bytearray()
        try:
            async with self._http.stream("POST", "/v1/audio/speech", json=payload) as response:
                if response.status_code != 200:
                    body = await response.aread()
                    raise OllamaError(
                        "Síntesis rechazada ({}): {} (voz: {})".format(
                            response.status_code,
                            body[:300].decode("utf-8", "replace"),
                            self._settings.voice,
                        )
                    )
                try:
                    async for chunk in response.aiter_bytes():
                        buffer.extend(chunk)
                except httpx.HTTPError:
                    # Cierre abrupto del stream: el audio recibido sigue siendo válido.
                    pass
        except httpx.HTTPError as exc:
            if not buffer:
                raise OllamaError("Fallo de red en la síntesis: {}".format(exc)) from exc

        audio = bytes(buffer)
        if not audio.startswith(b"RIFF"):
            raise OllamaError(
                "La síntesis no devolvió un WAV válido: {!r}".format(audio[:200])
            )
        return audio


def _clean_transcript(text: str) -> str:
    """Quita comillas, prefijos tipo "Transcripción:" y espacios sobrantes."""
    cleaned = (text or "").strip()
    if not cleaned:
        return ""
    lowered = cleaned.lower()
    for prefix in ("transcripción:", "transcripcion:", "texto:", "audio:"):
        if lowered.startswith(prefix):
            cleaned = cleaned[len(prefix):].strip()
            break
    cleaned = cleaned.strip().strip(chr(34)).strip(chr(39)).strip()
    return cleaned
