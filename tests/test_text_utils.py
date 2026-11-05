"""Pruebas de la limpieza de texto (respuesta y voz)."""
from __future__ import annotations

import unittest

from atlas.core.text_utils import to_speech_text


class TestMarkdown(unittest.TestCase):

    def test_quita_negritas_y_asteriscos(self):
        self.assertEqual(to_speech_text("**Hola** mundo"), "Hola mundo")

    def test_convierte_enlace_en_texto(self):
        self.assertEqual(
            to_speech_text("Ver [la fuente](https://ejemplo.com) para más"),
            "Ver la fuente para más",
        )

    def test_elimina_url_entre_parentesis(self):
        self.assertEqual(to_speech_text("Datos (https://x.com/a) aquí"), "Datos aquí")

    def test_quita_urls_sueltas(self):
        self.assertEqual(to_speech_text("mira https://x.com/a esto"), "mira esto")

    def test_quita_vinetas_y_numeracion(self):
        self.assertEqual(to_speech_text("- uno\n- dos\n1. tres"), "uno\ndos\ntres")

    def test_quita_encabezados(self):
        self.assertEqual(to_speech_text("## Título"), "Título")

    def test_conserva_contenido_de_codigo(self):
        self.assertEqual(to_speech_text("Usa `print(1)` aquí"), "Usa print(1) aquí")


class TestEmojisYSimbolos(unittest.TestCase):

    def test_quita_emojis(self):
        self.assertEqual(to_speech_text("Listo \U0001F680 ya esta \u2705"), "Listo ya esta")

    def test_quita_invisibles(self):
        self.assertEqual(to_speech_text("a\u200Bb\ufeffc"), "abc")


class TestTablas(unittest.TestCase):

    def test_colapsa_tabla_a_texto(self):
        texto = "| a | b |\n|---|---|\n| 1 | 2 |"
        self.assertEqual(to_speech_text(texto), "a b 1 2")


class TestPuntuacion(unittest.TestCase):

    def test_quita_espacio_antes_de_signo(self):
        self.assertEqual(to_speech_text("hola , mundo ."), "hola, mundo.")

    def test_colapsa_signos_repetidos(self):
        self.assertEqual(to_speech_text("espera...... ya"), "espera. ya")

    def test_quita_parentesis_vacios(self):
        self.assertEqual(to_speech_text("texto ( ) y [] fin"), "texto y fin")


class TestCasosLimite(unittest.TestCase):

    def test_texto_normal_intacto(self):
        self.assertEqual(to_speech_text("Buenos días, ¿qué tal?"), "Buenos días, ¿qué tal?")

    def test_vacio_y_none(self):
        self.assertEqual(to_speech_text(""), "")
        self.assertEqual(to_speech_text(None), "")

    def test_solo_simbolos(self):
        self.assertEqual(to_speech_text("** ## ~~"), "")


if __name__ == "__main__":
    unittest.main()
