"""Prueba de flujo completo, sin micrófono ni altavoz.

Se sustituyen los dispositivos y el cliente por dobles para verificar la
secuencia real: saludo → escucha → turno → respuesta → vuelta a escuchar.
"""
from __future__ import annotations

import asyncio
import base64
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

    async def test_acumula_tool_calls_de_varios_fragmentos(self):
        """En streaming, varios fragmentos con tool_calls se suman, no se pisan."""
        from unittest import mock

        ejecuciones = []

        async def fake_execute(nombre, argumentos):
            ejecuciones.append((nombre, argumentos))
            return "resultado"

        async def planner(messages, tools=None, options=None):
            if options and "num_predict" in options:
                yield {
                    "type": "tool_calls",
                    "calls": [{"function": {"name": "buscar_web", "arguments": {"consulta": "uno"}}}],
                }
                yield {
                    "type": "tool_calls",
                    "calls": [{"function": {"name": "buscar_web", "arguments": {"consulta": "dos"}}}],
                }
                return
            yield {"type": "token", "text": "Listo."}

        self.assistant.client.stream_events = planner
        with mock.patch("atlas.app.execute", fake_execute):
            await self.assistant._respond("dos búsquedas", 0.1)

        self.assertEqual(
            [argumentos for _, argumentos in ejecuciones],
            [{"consulta": "uno"}, {"consulta": "dos"}],
        )

    async def test_segunda_ronda_de_herramienta(self):
        """Si el modelo pide otra búsqueda tras ver los resultados, se ejecuta."""
        from unittest import mock

        ejecuciones = []
        finales = {"n": 0}

        async def fake_execute(nombre, argumentos):
            ejecuciones.append((nombre, argumentos))
            return "resultado"

        async def planner(messages, tools=None, options=None):
            if options and "num_predict" in options:
                yield {
                    "type": "tool_calls",
                    "calls": [{"function": {"name": "buscar_web", "arguments": {"consulta": "primera"}}}],
                }
                return
            finales["n"] += 1
            if finales["n"] == 1:
                yield {
                    "type": "tool_calls",
                    "calls": [{"function": {"name": "buscar_web", "arguments": {"consulta": "segunda"}}}],
                }
                return
            yield {"type": "token", "text": "Respuesta final."}

        self.assistant.client.stream_events = planner
        with mock.patch("atlas.app.execute", fake_execute):
            await self.assistant._respond("pregunta", 0.1)

        self.assertEqual(
            [argumentos for _, argumentos in ejecuciones],
            [{"consulta": "primera"}, {"consulta": "segunda"}],
        )
        self.assertIn("Respuesta final", self.assistant.history[-1]["content"])

    async def test_conserva_contenido_y_thinking_en_el_mensaje(self):
        """El mensaje del asistente lleva content y thinking, no solo tool_calls."""
        from unittest import mock

        capturado = {}

        async def planner(messages, tools=None, options=None):
            if options and "num_predict" in options:
                yield {"type": "thinking", "text": "pienso"}
                yield {"type": "token", "text": "Voy a buscar. "}
                yield {
                    "type": "tool_calls",
                    "calls": [{"function": {"name": "buscar_web", "arguments": {"consulta": "x"}}}],
                }
                return
            capturado["mensajes"] = list(messages)
            yield {"type": "token", "text": "ok"}

        self.assistant.client.stream_events = planner
        with mock.patch("atlas.app.execute", mock.AsyncMock(return_value="r")):
            await self.assistant._respond("pregunta", 0.1)

        asistente = next(m for m in capturado["mensajes"] if m["role"] == "assistant")
        self.assertEqual(asistente["thinking"], "pienso")
        self.assertEqual(asistente["content"], "Voy a buscar. ")
        self.assertEqual(
            asistente["tool_calls"][0]["function"]["arguments"], {"consulta": "x"}
        )


    async def test_mensaje_con_imagen_lleva_base64(self):
        imagen = b"\xff\xd8foto"
        mensajes = self.assistant._messages_for("¿qué ves?", image=imagen)
        self.assertEqual(mensajes[-1]["role"], "user")
        self.assertEqual(
            mensajes[-1]["images"], [base64.b64encode(imagen).decode("ascii")]
        )
        self.assertTrue(
            any(
                "imagen" in m.get("content", "").lower()
                for m in mensajes
                if m["role"] == "system"
            )
        )

    async def test_respuesta_envia_imagen_solo_en_la_llamada_final(self):
        capturado = {}

        async def planner(messages, tools=None, options=None):
            if options and "num_predict" in options:
                capturado["decision"] = list(messages)
                return
            capturado["final"] = list(messages)
            yield {"type": "token", "text": "Es una taza."}

        self.assistant.client.stream_events = planner
        imagen = b"\xff\xd8foto"
        await self.assistant._respond("¿qué ves?", 0.1, image=imagen)

        self.assertNotIn("images", capturado["decision"][-1])
        self.assertEqual(
            capturado["final"][-1]["images"],
            [base64.b64encode(imagen).decode("ascii")],
        )
        self.assertIn("taza", self.assistant.history[-1]["content"])

    async def test_supports_vision_lee_capacidades(self):
        class Respuesta:
            status_code = 200

            def json(self):
                return {"capabilities": ["completion", "vision"]}

        class Http:
            async def post(self, *args, **kwargs):
                return Respuesta()

        original = self.assistant.client._http
        self.assistant.client._http = Http()
        try:
            self.assertTrue(await self.assistant.client.supports_vision())
        finally:
            self.assistant.client._http = original


    async def test_camara_ui_flujo(self):
        from unittest import mock

        class FakeCamera:
            def __init__(self, **kwargs):
                self.kwargs = kwargs
                self.started = False
                self.stopped = False
                self.active = False
                self.error = ""

            def start(self):
                self.started = True
                self.active = True

            def preview(self):
                return 1, b"preview"

            def snapshot(self):
                return b"snap"

            def stop(self):
                self.stopped = True
                self.active = False

        async def supports_vision():
            return True

        self.assistant.client.supports_vision = supports_vision
        with mock.patch("atlas.app.camera_available", return_value=True), mock.patch(
            "atlas.app.CameraWorker", FakeCamera
        ):
            await self.assistant._start_camera()
            self.assertTrue(self.assistant.camera_card.visible)
            self.assertTrue(self.assistant._camera_active)

            self.assistant._paint_camera()
            self.assertEqual(self.assistant.camera_image.src, b"preview")
            self.assertFalse(self.assistant.camera_snap_button.disabled)

            self.assistant._on_camera_snap()
            self.assertEqual(self.assistant._pending_image, b"snap")

            await self.assistant._stop_camera()
            self.assertFalse(self.assistant.camera_card.visible)
            self.assertIsNone(self.assistant._pending_image)
            self.assertFalse(self.assistant._camera_active)

    async def test_camara_sin_opencv(self):
        from unittest import mock

        with mock.patch("atlas.app.camera_available", return_value=False):
            await self.assistant._start_camera()
        self.assertFalse(self.assistant._camera_active)
        self.assertIn("OpenCV", self.assistant.status.value)


if __name__ == "__main__":
    unittest.main()
