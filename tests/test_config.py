"""Pruebas de configuración e identidad."""
from __future__ import annotations

import os
import unittest
from unittest import mock

from atlas.core.config import DEFAULT_NAME, Settings, load_settings


class TestDefaults(unittest.TestCase):

    def test_valores_por_defecto(self):
        s = load_settings()
        self.assertEqual(s.assistant_name, DEFAULT_NAME)
        self.assertEqual(s.model, "lfm3-omni:2b")
        self.assertEqual(s.sample_rate, 16000)
        self.assertEqual(s.voice, "male-spanish")
        self.assertTrue(s.web_search_enabled)
        self.assertTrue(s.hands_free)
        self.assertTrue(s.barge_in)
        self.assertEqual(s.camera_index, 0)
        self.assertEqual(s.camera_width, 1280)
        self.assertEqual(s.camera_height, 720)
        self.assertEqual(s.camera_preview_fps, 8.0)

    def test_no_depende_del_entorno(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            s = load_settings()
        self.assertEqual(s.assistant_name, "Atlas")


class TestVariablesDeEntorno(unittest.TestCase):

    def test_sobrescribe_por_entorno(self):
        env = {"VA_NAME": "Nova", "VA_VOICE": "male-spanish", "VA_HANDS_FREE": "0"}
        with mock.patch.dict(os.environ, env, clear=True):
            s = load_settings()
        self.assertEqual(s.assistant_name, "Nova")
        self.assertEqual(s.voice, "male-spanish")
        self.assertFalse(s.hands_free)

    def test_camara_por_entorno(self):
        env = {
            "VA_CAMERA_INDEX": "2",
            "VA_CAMERA_WIDTH": "640",
            "VA_CAMERA_HEIGHT": "480",
            "VA_CAMERA_PREVIEW_FPS": "5",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            s = load_settings()
        self.assertEqual(s.camera_index, 2)
        self.assertEqual(s.camera_width, 640)
        self.assertEqual(s.camera_height, 480)
        self.assertEqual(s.camera_preview_fps, 5.0)

    def test_valor_numerico_invalido_cae_al_defecto(self):
        with mock.patch.dict(os.environ, {"VA_VAD_SILENCE": "no-es-un-numero"}, clear=True):
            s = load_settings()
        self.assertEqual(s.vad_silence_s, 1.6)

    def test_bool_acepta_varias_formas(self):
        for valor in ("1", "true", "si", "on", "YES"):
            with mock.patch.dict(os.environ, {"VA_BARGE_IN": valor}, clear=True):
                self.assertTrue(load_settings().barge_in, valor)
        with mock.patch.dict(os.environ, {"VA_BARGE_IN": "0"}, clear=True):
            self.assertFalse(load_settings().barge_in)


class TestIdentidad(unittest.TestCase):

    def test_saludo_sustituye_el_nombre(self):
        s = load_settings(assistant_name="Nova")
        self.assertIn("Nova", s.greeting_text)
        self.assertNotIn("{name}", s.greeting_text)

    def test_prompt_sustituye_el_nombre(self):
        s = load_settings(assistant_name="Nova")
        self.assertIn("Te llamas Nova", s.system_text)

    def test_prompt_propio_con_llaves_no_falla(self):
        """Se usa replace, no format: unas llaves literales no deben romperlo."""
        s = load_settings(system_prompt="Eres {name}. Responde en JSON: {clave}")
        self.assertIn("Eres Atlas", s.system_text)
        self.assertIn("{clave}", s.system_text)

    def test_saludo_vacio_no_rompe(self):
        s = load_settings(greeting="")
        self.assertEqual(s.greeting_text, "")

    def test_settings_es_inmutable(self):
        s = Settings()
        with self.assertRaises(Exception):
            s.model = "otro"


if __name__ == "__main__":
    unittest.main()
