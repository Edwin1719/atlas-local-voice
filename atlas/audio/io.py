"""Captura y reproducción de audio con PortAudio (sounddevice).

Sustituye a flet-audio y flet-audio-recorder:
  - la tasa de muestreo es exactamente la que pedimos (no se adivina),
  - la reproducción es un buffer continuo alimentado por un callback, así que
    no hay cortes entre frases ni eventos que esperar,
  - permite elegir dispositivo por índice (clave cuando la salida es Bluetooth).
"""
from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass

import numpy as np
import sounddevice as sd

CAPTURE_RATE = 16000
PLAYBACK_RATE = 24000  # /v1/audio/speech devuelve 24 kHz
BLOCK = 1024


@dataclass(slots=True)
class DeviceInfo:
    index: int
    name: str
    channels: int
    rate: int

    def label(self, limit: int = 38) -> str:
        name = self.name if len(self.name) <= limit else self.name[:limit] + "…"
        return "{}: {}".format(self.index, name)


def _devices(want_input: bool) -> list[DeviceInfo]:
    found: list[DeviceInfo] = []
    for index, dev in enumerate(sd.query_devices()):
        channels = dev["max_input_channels"] if want_input else dev["max_output_channels"]
        if channels > 0:
            found.append(
                DeviceInfo(index, dev["name"], channels, int(dev["default_samplerate"]))
            )
    return found


def input_devices() -> list[DeviceInfo]:
    return _devices(True)


def output_devices() -> list[DeviceInfo]:
    return _devices(False)


def default_input_index() -> int | None:
    try:
        index = sd.default.device[0]
        return int(index) if index is not None and index >= 0 else None
    except Exception:
        return None


def default_output_index() -> int | None:
    try:
        index = sd.default.device[1]
        return int(index) if index is not None and index >= 0 else None
    except Exception:
        return None


class Recorder:
    """Captura continua en un hilo de PortAudio; el consumidor solo lee."""

    def __init__(self, device: int | None = None, rate: int = CAPTURE_RATE) -> None:
        self.device = device
        self.rate = rate
        self._buffer = bytearray()
        self._lock = threading.Lock()
        self._stream: sd.InputStream | None = None
        self.overflows = 0

    @property
    def active(self) -> bool:
        return self._stream is not None

    def start(self) -> None:
        with self._lock:
            self._buffer.clear()
        self.overflows = 0
        stream = sd.InputStream(
            samplerate=self.rate,
            channels=1,
            dtype="int16",
            device=self.device,
            blocksize=BLOCK,
            callback=self._callback,
        )
        stream.start()
        self._stream = stream

    def _callback(self, indata, frames, time_info, status) -> None:
        if status:
            self.overflows += 1
        with self._lock:
            self._buffer.extend(indata.tobytes())

    def take(self) -> bytes:
        """Devuelve y vacía lo capturado desde la llamada anterior."""
        with self._lock:
            if not self._buffer:
                return b""
            data = bytes(self._buffer)
            self._buffer.clear()
            return data

    def stop(self) -> None:
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.stop()
            except Exception:
                pass
            try:
                stream.close()
            except Exception:
                pass


class Player:
    """Cola de reproducción continua: sin cortes y con corte inmediato."""

    def __init__(self, device: int | None = None, rate: int = PLAYBACK_RATE) -> None:
        self.device = device
        self.rate = rate
        self._queue: queue.Queue[bytes] = queue.Queue()
        self._lock = threading.Lock()
        self._current = b""
        self._offset = 0
        self._stream: sd.OutputStream | None = None
        self._idle = threading.Event()
        self._idle.set()
        self.level = 0.0  # nivel RMS del bloque que suena, para animar la interfaz

    def start(self) -> None:
        if self._stream is not None:
            return
        stream = sd.OutputStream(
            samplerate=self.rate,
            channels=1,
            dtype="int16",
            device=self.device,
            blocksize=BLOCK,
            callback=self._callback,
        )
        stream.start()
        self._stream = stream

    def stop(self) -> None:
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.stop()
            except Exception:
                pass
            try:
                stream.close()
            except Exception:
                pass

    def enqueue(self, pcm: bytes) -> None:
        if not pcm:
            return
        self.start()
        self._idle.clear()
        self._queue.put(pcm)

    def clear(self) -> None:
        """Corta lo que suena y descarta lo pendiente (interrupción)."""
        with self._lock:
            while True:
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    break
            self._current = b""
            self._offset = 0
        self._idle.set()

    def _callback(self, outdata, frames, time_info, status) -> None:
        filled = 0
        while filled < frames:
            with self._lock:
                remaining = len(self._current) - self._offset
                if remaining < 2:
                    try:
                        chunk = self._queue.get_nowait()
                    except queue.Empty:
                        self._current = b""
                        self._offset = 0
                        break
                    self._current = chunk
                    self._offset = 0
                    remaining = len(chunk)
                    if remaining < 2:
                        continue
                samples_available = remaining // 2
                take = min(frames - filled, samples_available)
                start = self._offset
                self._offset += take * 2
                block = self._current[start : start + take * 2]
            outdata[filled : filled + take, 0] = np.frombuffer(block, dtype=np.int16)
            filled += take
        if filled < frames:
            outdata[filled:, 0] = 0
        if filled:
            block = outdata[:filled, 0].astype(np.float32)
            self.level = float(np.sqrt(np.mean(block * block)))
        else:
            self.level = 0.0
        with self._lock:
            drained = self._offset >= len(self._current) and self._queue.empty()
        if drained:
            self._idle.set()
        else:
            self._idle.clear()

    @property
    def idle(self) -> bool:
        return self._idle.is_set()

    def wait_done(self, timeout: float) -> bool:
        """Bloquea hasta que la cola se vacía. Llamar desde un hilo."""
        return self._idle.wait(max(0.1, timeout))
