"""Detección continua de voz y de interrupciones.

Sin dependencias externas. En lugar de un umbral fijo, estima el ruido de fondo
de la sala con una media exponencial y decide contra ese valor: funciona igual en
una habitación silenciosa que en una oficina con ventilador.

Estados internos:
    idle   -> esperando voz (acumula pre-roll para no cortar la primera sílaba)
    speech -> capturando el turno
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

SILENCE = "silence"
SPEECH_START = "speech_start"
TURN_READY = "turn_ready"
OVERFLOW = "overflow"


@dataclass(slots=True)
class Event:
    kind: str
    utterance: bytes = b""
    level: float = 0.0
    floor: float = 0.0


def rms(chunk: bytes) -> float:
    """Nivel eficaz de un bloque PCM16LE (0..32767)."""
    if len(chunk) < 2:
        return 0.0
    usable = len(chunk) - (len(chunk) % 2)
    samples = np.frombuffer(chunk[:usable], dtype=np.int16).astype(np.float32)
    if samples.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(samples * samples)))


class ContinuousDetector:
    def __init__(
        self,
        rate: int = 16000,
        preroll_s: float = 0.35,
        silence_s: float = 1.6,
        min_speech_s: float = 0.5,
        max_turn_s: float = 30.0,
        trigger_mult: float = 3.0,
        release_mult: float = 0.6,
        min_level: float = 200.0,
        floor_alpha: float = 0.05,
    ) -> None:
        self.rate = rate
        self._preroll_max = int(rate * 2 * preroll_s)
        self._silence_bytes = int(rate * 2 * silence_s)
        self._min_bytes = int(rate * 2 * min_speech_s)
        self._max_bytes = int(rate * 2 * max_turn_s)
        self._trigger_mult = trigger_mult
        self._release_mult = release_mult
        self._min_level = min_level
        self._alpha = floor_alpha

        self._preroll = bytearray()
        self._utterance = bytearray()
        self._state = "idle"
        self._floor = 0.0
        self._loud = 0
        self._silence = 0

    @property
    def floor(self) -> float:
        return self._floor

    @property
    def state(self) -> str:
        return self._state

    @property
    def trigger(self) -> float:
        return max(self._floor * self._trigger_mult, self._min_level)

    def reset(self) -> None:
        self._preroll.clear()
        self._utterance.clear()
        self._state = "idle"
        self._loud = 0
        self._silence = 0

    def seed(self, pcm: bytes) -> None:
        """Arranca un turno ya en curso (p. ej. tras una interrupción)."""
        self._utterance = bytearray(pcm)
        self._preroll.clear()
        self._state = "speech"
        self._loud = 0
        self._silence = 0

    def force_end(self) -> bytes:
        """Cierra el turno a mano (modo pulsar para hablar)."""
        data = bytes(self._utterance) or bytes(self._preroll)
        self.reset()
        return data

    def _push_preroll(self, chunk: bytes) -> None:
        self._preroll.extend(chunk)
        excess = len(self._preroll) - self._preroll_max
        if excess > 0:
            del self._preroll[:excess]

    def _finish(self, kind: str, level: float) -> Event:
        data = bytes(self._utterance)
        self._state = "idle"
        self._utterance.clear()
        self._silence = 0
        self._loud = 0
        return Event(kind, data, level, self._floor)

    def feed(self, chunk: bytes) -> Event:
        if len(chunk) < 2:
            return Event(SILENCE, level=0.0, floor=self._floor)
        if len(chunk) % 2:
            chunk = chunk[:-1]

        level = rms(chunk)
        if self._floor <= 0.0:
            # El suelo inicial se acota: si la primera muestra ya es voz, tomar su
            # nivel dejaría el disparo a 3x por encima y el turno nunca abriría.
            self._floor = max(25.0, min(level, 200.0))
        trigger = self.trigger

        if self._state == "idle":
            # El suelo solo se aprende cuando no hay voz, para no comerse el turno.
            self._floor = max(25.0, (1.0 - self._alpha) * self._floor + self._alpha * level)
            self._push_preroll(chunk)
            if level > trigger:
                self._loud += 1
            else:
                self._loud = 0
            if self._loud >= 2:  # dos bloques seguidos: no es un golpe aislado
                self._state = "speech"
                self._utterance = bytearray(self._preroll)
                self._utterance.extend(chunk)
                self._preroll.clear()
                self._silence = 0
                self._loud = 0
                return Event(SPEECH_START, level=level, floor=self._floor)
            return Event(SILENCE, level=level, floor=self._floor)

        self._utterance.extend(chunk)
        if level > trigger * self._release_mult:
            self._silence = 0
        else:
            self._silence += len(chunk)

        if len(self._utterance) >= self._max_bytes:
            return self._finish(OVERFLOW, level)
        if self._silence >= self._silence_bytes and len(self._utterance) >= self._min_bytes:
            return self._finish(TURN_READY, level)
        return Event(SILENCE, level=level, floor=self._floor)


class BargeMonitor:
    """Decide si lo que entra por el micrófono es el usuario interrumpiendo.

    Durante la reproducción hay eco del altavoz. Exigimos un nivel claramente
    superior al ruido de fondo y sostenido en el tiempo, no un pico suelto.
    """

    def __init__(
        self,
        rate: int = 16000,
        mult: float = 2.5,
        min_level: float = 400.0,
        need_s: float = 0.30,
    ) -> None:
        self._need_bytes = int(rate * 2 * need_s)
        self._mult = mult
        self._min_level = min_level
        self._acc = 0

    def reset(self) -> None:
        self._acc = 0

    def feed(self, chunk: bytes, floor: float) -> bool:
        level = rms(chunk)
        threshold = max(floor * self._mult, self._min_level)
        if level > threshold:
            self._acc += len(chunk)
        else:
            self._acc = 0
        return self._acc >= self._need_bytes
