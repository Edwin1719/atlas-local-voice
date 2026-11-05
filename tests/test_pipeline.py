"""Prueba de flujo completo, sin micrófono ni altavoz.

Se sustituyen los dispositivos y el cliente por dobles para verificar la
secuencia real: saludo → escucha → turno → respuesta → vuelta a escuchar.
"""
from __future__ import annotations

import asyncio
import unittest

import numpy as np

from atlas.app import IDLE, LISTENING, VoiceAssistant
from atlas.core.audio_utils import pcm16_to_wav
from atlas.core.config import load_settings

RATE = 16000


def bloque(nivel: int, segundos: float = 0.1) -> bytes:
    return np.full(int(RATE * segundos), nivel, dtype=np.int16).tobytes()


class PaginaFalsa:
    def __init__(self):
        self.services = []
        self.title = None
        self.bgcolor = None
        self.padding = 0
        self.theme_mode = None
        self.on_disconnect = None

    def add(self, *args, **kwargs):
        pass

    def update(self, *args, **kwargs):
        pass

    def run_task(self, handler, *args, **kwargs):
        return asyncio.get_running_loop().create_task(handler(*args, **kwargs))


class GrabadorFalso:
    rate = RATE

    def __init__(self):
        self.active = False
        self.chunks: list[bytes] = []

    def start(self):
        self.active = True

    def stop(self):
        self.active = False

    def take(self):
        return self.chunks.pop(0) if self.chunks else b""


class ReproductorFalso:
    rate = 24000

    def __init__(self):
        self.level = 0.0
        self.clips: list[int] = []
        self.clears = 0

    def start(self):
        pass

    def enqueue(self, pcm: bytes):
        self.clips.append(len(pcm))

    def clear(self):
        self.clears += 1

    def stop(self):
        pass

    def wait_done(self, timeout):
        return True


class TestFlujoCompleto(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        settings = load_settings(greeting="Hola, me llamo Atlas.", hands_free=True)
        self.assistant = VoiceAssistant(PaginaFalsa(), settings)
        self.recorder = GrabadorFalso()
        self.player = ReproductorFalso()
        self.assistant.recorder = self.recorder
        self.assistant.player = self.player

        cliente = self.assistant.client

        async def ensure_model():
            return None

        async def transcribe(pcm):
            self.audio_transcrito = pcm
            return "hola atlas"

        async def stream_events(messages, tools=None, options=None):
            # La llamada de decisión es la única con salida acotada (num_predict).
            # Aquí se decide "no buscar"; la segunda llamada redacta.
            if options and "num_predict" in options:
                return
            for trozo in ["Hola, ", "te escucho."]:
                yield {"type": "token", "text": trozo}

        async def stream_chat(messages):
            for trozo in ["Hola, ", "te escucho."]:
                yield trozo

        async def synthesize(texto):
            return pcm16_to_wav(bytes(12000), 24000)

        cliente.ensure_model = ensure_model
        cliente.transcribe = transcribe
        cliente.stream_events = stream_events
        cliente.stream_chat = stream_chat
        cliente.synthesize = synthesize

        await asyncio.sleep(0.3)  # deja terminar _startup y el saludo

    async def asyncTearDown(self):
        self.assistant._closing = True
        await self.assistant.shutdown()

    async def test_arranque_saluda_y_queda_escuchando(self):
        self.assertEqual(self.assistant.state, LISTENING)
        self.assertTrue(self.recorder.active)
        self.assertGreaterEqual(len(self.player.clips), 1)
        self.assertIn("Atlas", self.assistant.answer_text.value)

    async def test_un_turno_completo(self):
        self.recorder.chunks = (
            [bloque(8)] * 6 + [bloque(3000)] * 10 + [bloque(8)] * 20
        )
        for _ in range(80):
            await asyncio.sleep(0.05)
            if self.assistant.history:
                break

        self.assertEqual(len(self.assistant.history), 2)
        self.assertEqual(self.assistant.history[0]["role"], "user")
        self.assertEqual(self.assistant.history[1]["role"], "assistant")
        self.assertIn("hola atlas", self.assistant.history[0]["content"])
        self.assertIn("hola atlas", self.assistant.user_text.value)

    async def test_vuelve_a_escuchar_tras_responder(self):
        self.recorder.chunks = [bloque(8)] * 6 + [bloque(3000)] * 10 + [bloque(8)] * 20
        for _ in range(80):
            await asyncio.sleep(0.05)
            if self.assistant.history:
                break
        await asyncio.sleep(0.2)
        self.assertEqual(self.assistant.state, LISTENING)
        self.assertTrue(self.recorder.active)

    async def test_audio_corto_no_genera_turno(self):
        self.recorder.chunks = [bloque(8)] * 4 + [bloque(3000)] * 2 + [bloque(8)] * 10
        await asyncio.sleep(0.6)
        self.assertEqual(self.assistant.history, [])

    async def test_detener_corta_y_reanuda(self):
        self.assistant._set_state("speaking")
        await self.assistant._stop_everything()
        self.assertGreaterEqual(self.player.clears, 1)
        self.assertEqual(self.assistant.state, LISTENING)

    async def test_herramienta_se_ejecuta_cuando_el_modelo_la_pide(self):
        """Si la llamada de decisión emite tool_calls, se ejecuta y se responde."""
        from unittest import mock

        ejecuciones = []

        async def fake_execute(nombre, argumentos):
            ejecuciones.append((nombre, argumentos))
            return "Resultado simulado de la búsqueda"

        async def planner_con_herramienta(messages, tools=None, options=None):
            if options and "num_predict" in options:
                yield {
                    "type": "tool_calls",
                    "calls": [{"function": {"name": "buscar_web", "arguments": {"consulta": "prueba"}}}],
                }
                return
            yield {"type": "token", "text": "Según la búsqueda, todo en orden."}

        self.assistant.client.stream_events = planner_con_herramienta
        with mock.patch("atlas.app.execute", fake_execute):
            await self.assistant._respond("¿qué pasa hoy?", 0.1)

        self.assertEqual(len(ejecuciones), 1)
        self.assertEqual(ejecuciones[0][0], "buscar_web")
        self.assertEqual(ejecuciones[0][1], {"consulta": "prueba"})
        self.assertIn("búsqueda", self.assistant.history[-1]["content"])

if __name__ == "__main__":
    unittest.main()
