"""Utilidades de audio: conversión PCM16 ↔ WAV.

Solo stdlib. Se evita el módulo audioop porque desapareció en Python 3.13.
"""
from __future__ import annotations

import io
import wave

BYTES_PER_SAMPLE = 2


def wav_to_pcm(data: bytes) -> tuple[bytes, int, int]:
    """Extrae (pcm, tasa, canales) de un WAV.

    Tolera cabeceras con tamaño de datos falso: el WAV que devuelve Ollama por
    streaming puede declarar horas de audio para un clip de medio segundo, así
    que la carga útil se localiza buscando el chunk "data" y se mide por longitud.
    """
    if len(data) < 44:
        return b"", 24000, 1
    try:
        rate = int.from_bytes(data[24:28], "little") or 24000
        channels = int.from_bytes(data[22:24], "little") or 1
    except Exception:
        rate, channels = 24000, 1
    marker = data.find(b"data", 0, 200)
    start = marker + 8 if marker >= 0 else 44
    return data[start:], rate, channels


def pcm16_to_wav(pcm: bytes, sample_rate: int, channels: int = 1) -> bytes:
    """Envuelve PCM16LE crudo en un contenedor WAV válido.

    Ollama no acepta PCM suelto: input_audio espera un contenedor.
    """
    frame = BYTES_PER_SAMPLE * channels
    usable = len(pcm) - (len(pcm) % frame) if frame else 0
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(BYTES_PER_SAMPLE)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm[:usable])
    return buffer.getvalue()
