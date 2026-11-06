"""Pruebas de la captura de cámara, sin hardware ni OpenCV real."""
from __future__ import annotations

import time
import types
import unittest
from unittest import mock

import numpy as np

from atlas.vision.camera import CameraWorker, camera_available


class _Buffer:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def tobytes(self) -> bytes:
        return self._data


class _Capture:
    def __init__(self, frame: np.ndarray) -> None:
        self.frame = frame
        self.released = False

    def isOpened(self) -> bool:
        return True

    def set(self, *args) -> None:
        pass

    def read(self):
        time.sleep(0.005)
        return True, self.frame.copy()

    def release(self) -> None:
        self.released = True


class _ClosedCapture(_Capture):
    def isOpened(self) -> bool:
        return False


def _fake_cv2(capture_cls=_Capture):
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    return types.SimpleNamespace(
        CAP_DSHOW=0,
        CAP_ANY=0,
        CAP_PROP_FRAME_WIDTH=3,
        CAP_PROP_FRAME_HEIGHT=4,
        CAP_PROP_FPS=5,
        IMWRITE_JPEG_QUALITY=1,
        VideoCapture=lambda index, backend: capture_cls(frame),
        resize=lambda image, size: image,
        imencode=lambda ext, image, params: (True, _Buffer(b"jpeg")),
    )


def _wait_for(predicate, timeout=2.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


class TestCameraWorker(unittest.TestCase):

    def test_preview_y_snapshot(self):
        worker = CameraWorker(preview_fps=50)
        with mock.patch("atlas.vision.camera._load_cv2", return_value=_fake_cv2()):
            worker.start()
            self.assertTrue(_wait_for(lambda: worker.preview()[1] is not None))
            seq, preview = worker.preview()
            self.assertGreater(seq, 0)
            self.assertEqual(preview, b"jpeg")
            self.assertEqual(worker.snapshot(), b"jpeg")
            worker.stop()
        self.assertFalse(worker.active)

    def test_snapshot_sin_fotograma(self):
        worker = CameraWorker()
        self.assertIsNone(worker.snapshot())

    def test_sin_opencv(self):
        worker = CameraWorker()
        with mock.patch("atlas.vision.camera._load_cv2", return_value=None):
            worker.start()
        self.assertFalse(worker.active)
        self.assertIn("OpenCV", worker.error)

    def test_camara_no_disponible(self):
        worker = CameraWorker()
        with mock.patch(
            "atlas.vision.camera._load_cv2", return_value=_fake_cv2(_ClosedCapture)
        ):
            worker.start()
            self.assertTrue(_wait_for(lambda: "No se pudo abrir" in worker.error))
            worker.stop()
        self.assertIn("No se pudo abrir", worker.error)

    def test_disponibilidad(self):
        with mock.patch(
            "atlas.vision.camera._load_cv2", return_value=_fake_cv2()
        ):
            self.assertTrue(camera_available())
        with mock.patch("atlas.vision.camera._load_cv2", return_value=None):
            self.assertFalse(camera_available())


if __name__ == "__main__":
    unittest.main()
