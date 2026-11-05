"""Pruebas de conversión PCM ↔ WAV.

Cubren el fallo que congeló la aplicación: Ollama devuelve WAV con una
cabecera cuyo tamaño de datos no corresponde con los bytes reales.
"""
from __future__ import annotations

import unittest

from atlas.core.audio_utils import pcm16_to_wav, wav_to_pcm


class TestWavConversion(unittest.TestCase):

    def test_ida_y_vuelta_conserva_longitud(self):
        pcm = bytes(3200)  # 100 ms a 16 kHz mono
        wav = pcm16_to_wav(pcm, 16000)
        recuperado, rate, channels = wav_to_pcm(wav)
        self.assertEqual(rate, 16000)
        self.assertEqual(channels, 1)
        self.assertEqual(len(recuperado), len(pcm))

    def test_respeta_la_tasa(self):
        for rate in (16000, 24000, 44100):
            wav = pcm16_to_wav(bytes(480), rate)
            _, leido, _ = wav_to_pcm(wav)
            self.assertEqual(leido, rate)

    def test_ignora_el_tamano_falso_de_la_cabecera(self):
        """El caso real: cabecera que declara horas de audio para 0,5 s."""
        pcm = bytes(24000)  # 0,5 s a 24 kHz
        wav = bytearray(pcm16_to_wav(pcm, 24000))
        # el chunk de datos empieza en 40 y su tamaño va en 40..44
        wav[40:44] = (0xFFFFFFFF).to_bytes(4, "little")
        recuperado, rate, _ = wav_to_pcm(bytes(wav))
        self.assertEqual(rate, 24000)
        self.assertEqual(len(recuperado), len(pcm))

    def test_pcm_impar_se_recorta(self):
        wav = pcm16_to_wav(b"\x00" * 1001, 16000)
        recuperado, _, _ = wav_to_pcm(wav)
        self.assertEqual(len(recuperado) % 2, 0)
        self.assertLessEqual(len(recuperado), 1001)

    def test_entrada_vacia_o_corrupta(self):
        self.assertEqual(wav_to_pcm(b"")[0], b"")
        self.assertEqual(len(wav_to_pcm(b"RIFF")[0]), 0)
        wav = pcm16_to_wav(b"", 16000)
        self.assertEqual(wav_to_pcm(wav)[0], b"")

    def test_cabecera_wav_valida(self):
        wav = pcm16_to_wav(bytes(160), 16000)
        self.assertTrue(wav.startswith(b"RIFF"))
        self.assertEqual(wav[8:12], b"WAVE")


if __name__ == "__main__":
    unittest.main()
