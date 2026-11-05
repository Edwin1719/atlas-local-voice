"""Pruebas del detector de turno y del monitor de interrupción."""
from __future__ import annotations

import unittest

import numpy as np

from atlas.audio.dialog import (
    OVERFLOW,
    SPEECH_START,
    TURN_READY,
    BargeMonitor,
    ContinuousDetector,
    rms,
)

RATE = 16000
CHUNK = RATE // 10  # 100 ms de audio por bloque


def bloque(nivel: int, segundos: float = 0.1) -> bytes:
    muestras = int(RATE * segundos)
    return np.full(muestras, nivel, dtype=np.int16).tobytes()


def alimentar(detector: ContinuousDetector, audio: bytes) -> list:
    eventos = []
    paso = CHUNK * 2
    for i in range(0, len(audio), paso):
        evento = detector.feed(audio[i : i + paso])
        if evento.kind != "silence":
            eventos.append(evento)
    return eventos


class TestNivel(unittest.TestCase):

    def test_rms_de_silencio_y_de_voz(self):
        self.assertEqual(rms(bytes(320)), 0.0)
        self.assertAlmostEqual(rms(bloque(1000)), 1000.0, delta=1.0)

    def test_rms_tolera_bloques_impares(self):
        self.assertGreater(rms(b"\x01\x02\x03"), 0.0)
        self.assertEqual(rms(b"\x01"), 0.0)


class TestDeteccionDeTurno(unittest.TestCase):

    def test_silencio_voz_silencio_genera_un_turno(self):
        detector = ContinuousDetector(rate=RATE)
        audio = bloque(10, 1.0) + bloque(3000, 1.5) + bloque(10, 2.5)
        eventos = alimentar(detector, audio)

        tipos = [e.kind for e in eventos]
        self.assertIn(SPEECH_START, tipos)
        self.assertEqual(tipos[-1], TURN_READY)

        turno = eventos[-1].utterance
        segundos = len(turno) / (RATE * 2)
        # pre-roll 0,35 + voz 1,5 + silencio 1,6 (aproximado)
        self.assertGreater(segundos, 2.5)
        self.assertLess(segundos, 4.5)

    def test_ruido_de_fondo_continuo_no_abre_turno(self):
        detector = ContinuousDetector(rate=RATE)
        ruido = np.random.normal(0, 300, RATE * 4).astype(np.int16).tobytes()
        eventos = alimentar(detector, ruido)
        self.assertEqual(eventos, [])

    def test_detecta_voz_sobre_ruido_de_fondo(self):
        detector = ContinuousDetector(rate=RATE)
        ruido = np.random.normal(0, 300, RATE * 2).astype(np.int16).tobytes()
        alimentar(detector, ruido)
        eventos = alimentar(detector, bloque(3000, 1.2) + ruido)
        self.assertTrue(any(e.kind == TURN_READY for e in eventos))

    def test_un_golpe_aislado_no_abre_turno(self):
        detector = ContinuousDetector(rate=RATE)
        eventos = alimentar(detector, bloque(10, 1.0))
        eventos += alimentar(detector, bloque(9000, 0.1))
        eventos += alimentar(detector, bloque(10, 2.0))
        self.assertEqual([e.kind for e in eventos if e.kind != TURN_READY], [])

    def test_corte_por_duracion_maxima(self):
        detector = ContinuousDetector(rate=RATE, max_turn_s=2.0)
        eventos = alimentar(detector, bloque(3000, 4.0))
        self.assertTrue(any(e.kind == OVERFLOW for e in eventos))

    def test_seed_continua_un_turno_en_curso(self):
        detector = ContinuousDetector(rate=RATE)
        detector.seed(bloque(3000, 0.5))
        eventos = alimentar(detector, bloque(3000, 0.6) + bloque(10, 2.0))
        self.assertTrue(any(e.kind == TURN_READY for e in eventos))
        self.assertGreater(len(eventos[-1].utterance), RATE)

    def test_force_end_devuelve_lo_acumulado(self):
        detector = ContinuousDetector(rate=RATE)
        alimentar(detector, bloque(10, 0.5) + bloque(3000, 0.8))
        audio = detector.force_end()
        self.assertGreater(len(audio), 0)
        self.assertEqual(detector.state, "idle")

    def test_reset_limpia_el_estado(self):
        detector = ContinuousDetector(rate=RATE)
        alimentar(detector, bloque(3000, 0.8))
        detector.reset()
        self.assertEqual(detector.state, "idle")
        self.assertEqual(len(detector.force_end()), 0)


class TestMonitorDeInterrupcion(unittest.TestCase):

    def test_el_eco_suave_no_interrumpe(self):
        monitor = BargeMonitor(rate=RATE, mult=3.0, min_level=500, need_s=0.35)
        resultados = [monitor.feed(bloque(300), 100) for _ in range(10)]
        self.assertFalse(any(resultados))

    def test_la_voz_sostenida_interrumpe(self):
        monitor = BargeMonitor(rate=RATE, mult=3.0, min_level=500, need_s=0.35)
        resultados = [monitor.feed(bloque(3000), 100) for _ in range(6)]
        self.assertTrue(any(resultados))

    def test_un_pico_aislado_no_interrumpe(self):
        monitor = BargeMonitor(rate=RATE, mult=3.0, min_level=500, need_s=0.35)
        self.assertFalse(monitor.feed(bloque(9000, 0.1), 100))
        self.assertFalse(monitor.feed(bloque(100), 100))

    def test_reset_reinicia_el_contador(self):
        monitor = BargeMonitor(rate=RATE, mult=3.0, min_level=500, need_s=0.35)
        [monitor.feed(bloque(3000), 100) for _ in range(3)]
        monitor.reset()
        self.assertFalse(monitor.feed(bloque(3000), 100))


if __name__ == "__main__":
    unittest.main()
