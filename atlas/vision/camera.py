"""Captura de cámara en un hilo separado.

OpenCV se importa de forma perezosa: la cámara es una función adicional y el
resto del asistente debe arrancar aunque no esté instalada. El hilo solo captura
y codifica; el bucle asyncio lee el último JPEG y nunca toca el dispositivo.
"""
from __future__ import annotations

import sys
import threading
import time

cv2 = None


def _load_cv2():
    """Importa OpenCV solo cuando se usa la cámara."""
    global cv2
    if cv2 is None:
        try:
            import cv2 as _cv2
        except ImportError:  # la cámara es opcional
            return None
        cv2 = _cv2
    return cv2


def camera_available() -> bool:
    """True si OpenCV está instalado y la cámara se puede intentar abrir."""
    return _load_cv2() is not None


class CameraWorker:
    """Hilo de captura con vista previa JPEG y snapshot bajo demanda."""

    def __init__(
        self,
        index: int = 0,
        width: int = 1280,
        height: int = 720,
        preview_width: int = 640,
        preview_quality: int = 60,
        preview_fps: float = 8.0,
        snapshot_quality: int = 85,
    ) -> None:
        self.index = index
        self.width = width
        self.height = height
        self.preview_width = preview_width
        self.preview_quality = preview_quality
        self.preview_interval = 1.0 / max(1.0, preview_fps)
        self.snapshot_quality = snapshot_quality

        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._frame = None
        self._preview: bytes | None = None
        self._seq = 0
        self._error = ""
        self._thread: threading.Thread | None = None
        self._cv2 = None

    @property
    def active(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def error(self) -> str:
        return self._error

    def start(self) -> None:
        if self.active:
            return
        motor = _load_cv2()
        if motor is None:
            self._error = "OpenCV no está instalado."
            return
        self._cv2 = motor
        self._stop.clear()
        self._error = ""
        self._seq = 0
        self._preview = None
        self._frame = None
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=2.0)

    def preview(self) -> tuple[int, bytes | None]:
        with self._lock:
            return self._seq, self._preview

    def snapshot(self) -> bytes | None:
        with self._lock:
            frame = None if self._frame is None else self._frame.copy()
        cv2 = self._cv2
        if frame is None or cv2 is None:
            return None
        ok, buffer = cv2.imencode(
            ".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), self.snapshot_quality]
        )
        return buffer.tobytes() if ok else None

    def _open(self):
        cv2 = self._cv2
        if cv2 is None:
            return None
        backends = [cv2.CAP_DSHOW, cv2.CAP_ANY] if sys.platform == "win32" else [cv2.CAP_ANY]
        for backend in backends:
            capture = cv2.VideoCapture(self.index, backend)
            if capture.isOpened():
                return capture
            capture.release()
        return None

    def _run(self) -> None:
        cv2 = self._cv2
        capture = self._open()
        if capture is None or cv2 is None:
            self._error = "No se pudo abrir la cámara."
            return
        capture.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        capture.set(cv2.CAP_PROP_FPS, 30)
        last_preview = 0.0
        try:
            while not self._stop.is_set():
                ok, frame = capture.read()
                if not ok:
                    self._error = "La cámara no entrega imagen."
                    time.sleep(0.1)
                    continue
                with self._lock:
                    self._frame = frame
                    self._error = ""
                now = time.monotonic()
                if now - last_preview >= self.preview_interval:
                    height = max(
                        1,
                        int(
                            self.preview_width
                            * frame.shape[0]
                            / max(1, frame.shape[1])
                        ),
                    )
                    small = cv2.resize(frame, (self.preview_width, height))
                    ok, buffer = cv2.imencode(
                        ".jpg", small, [int(cv2.IMWRITE_JPEG_QUALITY), self.preview_quality]
                    )
                    if ok:
                        with self._lock:
                            self._preview = buffer.tobytes()
                            self._seq += 1
                        last_preview = now
        finally:
            capture.release()
