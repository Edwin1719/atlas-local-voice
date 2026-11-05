"""Asistente de voz local (voz a voz) con Flet y LFM3-Omni-2B sobre Ollama.

Un turno: micrófono (PCM16) -> fin de turno por VAD -> transcripción
-> respuesta en streaming -> síntesis por frase -> reproducción.

Principio de diseño: ninguna ruta puede dejar la UI bloqueada. Todo turno
termina en un bloque finally que restaura el estado y devuelve el control.
"""
from __future__ import annotations

import asyncio
import json
import math
import time
from dataclasses import replace

import flet as ft

from atlas.audio.dialog import (
    OVERFLOW,
    SPEECH_START,
    TURN_READY,
    BargeMonitor,
    ContinuousDetector,
    rms,
)
from atlas.audio.io import (
    Player,
    Recorder,
    default_input_index,
    default_output_index,
    input_devices,
    output_devices,
)
from atlas.core.audio_utils import wav_to_pcm
from atlas.core.text_utils import to_speech_text
from atlas.core.config import Settings, load_settings
from atlas.llm.client import OllamaError, VoiceClient
from atlas.tools import TOOLS, execute

IDLE = "idle"
LISTENING = "listening"
THINKING = "thinking"
SPEAKING = "speaking"

BG = "#0b0d12"
SURFACE = "#141821"
SURFACE_ALT = "#1b2029"
LINE = "#262c38"
TEXT = "#e8ecf3"
MUTED = "#8d97a8"
ACCENT = "#38bdf8"
ACCENT_DARK = "#0284c7"
DANGER = "#ef4444"
WARN = "#f59e0b"
OK = "#22c55e"

BUBBLE_USER = "#16344d"
BUBBLE_BOT = "#1c2230"

STATE_LABEL = {
    IDLE: "Listo",
    LISTENING: "Escuchando",
    THINKING: "Pensando",
    SPEAKING: "Hablando",
}
STATE_COLOR = {
    IDLE: OK,
    LISTENING: DANGER,
    THINKING: WARN,
    SPEAKING: ACCENT,
}

SENTENCE_END = ".!?…\n"

TRANSCRIBE_TIMEOUT = 90.0
PRODUCE_TIMEOUT = 120.0
TTS_TIMEOUT = 45.0


class SentenceSplitter:
    """Acumula tokens y entrega frases completas para no esperar al final."""

    MIN_CHARS = 30
    MAX_CHARS = 220

    def __init__(self) -> None:
        self._buffer = ""

    def push(self, token: str) -> list[str]:
        self._buffer += token
        ready: list[str] = []
        while True:
            cut = self._boundary()
            if cut < 0:
                break
            piece = self._buffer[: cut + 1].strip()
            self._buffer = self._buffer[cut + 1 :].lstrip()
            if piece:
                ready.append(piece)
        return ready

    def _boundary(self) -> int:
        """Corta en . ! ? seguidos de espacio, o si el texto se hace muy largo.

        Antes se cortaba con solo 8 caracteres y también en saltos de línea y
        puntos suspensivos: eso partía la respuesta en trozos diminutos y la voz
        sonaba entrecortada.
        """
        length = len(self._buffer)
        for index, char in enumerate(self._buffer):
            if char not in ".!?":
                continue
            at_end = index + 1 >= length
            followed_by_space = (not at_end) and self._buffer[index + 1] in " \n"
            if not (at_end or followed_by_space):
                continue
            if len(self._buffer[: index + 1].strip()) >= self.MIN_CHARS:
                return index
        if length > self.MAX_CHARS:
            cut = self._buffer.rfind(",", 0, self.MAX_CHARS)
            if cut < 0:
                cut = self._buffer.rfind(" ", 0, self.MAX_CHARS)
            if cut > 0:
                return cut
        return -1

    def flush(self) -> str:
        rest = self._buffer.strip()
        self._buffer = ""
        return rest


class VoiceAssistant:
    def __init__(self, page: ft.Page, settings: Settings) -> None:
        self.page = page
        self.settings = settings
        self.client = VoiceClient(settings)

        self.state = IDLE
        self.pcm = bytearray()
        self.detector = self._make_detector(settings)
        self.barge = BargeMonitor(
            rate=settings.sample_rate,
            mult=settings.barge_mult,
            min_level=settings.barge_min_level,
            need_s=settings.barge_sustain_s,
        )
        self.history: list[dict[str, str]] = []
        self._odd_byte = b""
        self._pending = b""
        self._mic_level = 0.0
        self._closing = False
        self._turn_task = None
        self._audio_task = None
        self._animate_task = None
        self._stop_requested = False
        self._timings: dict[str, float] = {}
        self._captured_seconds = 0.0
        self._first_message_shown = False

        self.recorder = Recorder(device=settings.input_device, rate=settings.sample_rate)
        self.player = Player(device=settings.output_device, rate=24000)

        self._build_ui()
        page.run_task(self._startup)

    def _make_detector(self, settings: Settings) -> ContinuousDetector:
        return ContinuousDetector(
            rate=settings.sample_rate,
            preroll_s=settings.preroll_s,
            silence_s=settings.vad_silence_s,
            min_speech_s=settings.vad_min_speech_s,
            max_turn_s=settings.vad_max_turn_s,
        )

    # ------------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        page = self.page
        page.title = "ATLAS · asistente de voz"
        page.bgcolor = BG
        page.padding = 0
        page.theme_mode = ft.ThemeMode.DARK

        # ---------------------------------------------------------- cabecera
        self.state_dot = ft.Container(width=7, height=7, border_radius=4, bgcolor=OK)
        self.state_label = ft.Text("Iniciando", size=11, color=TEXT, weight=ft.FontWeight.W_600)
        self.state_pill = ft.Container(
            content=ft.Row(controls=[self.state_dot, self.state_label], spacing=7),
            padding=ft.Padding(left=12, top=7, right=14, bottom=7),
            border_radius=20,
            bgcolor="#0b1622",
            border=ft.Border.all(1, "#132b3a"),
        )

        marca = ft.Column(
            controls=[
                ft.Text("A T L A S", size=15, weight=ft.FontWeight.BOLD, color="#e8fbff"),
                ft.Text("asistente de voz · local", size=9, color="#4d6b7a"),
            ],
            spacing=0,
        )
        cabecera = ft.Container(
            content=ft.Row(
                controls=[
                    ft.Container(
                        content=ft.Icon(ft.Icons.GRAPHIC_EQ, color="#04121a", size=18),
                        padding=9,
                        border_radius=12,
                        gradient=ft.LinearGradient(colors=["#67e8f9", "#0ea5e9"]),
                    ),
                    marca,
                    ft.Container(expand=True),
                    self.state_pill,
                ],
                spacing=12,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.Padding(left=22, top=16, right=22, bottom=16),
            gradient=ft.LinearGradient(colors=["#080f18", "#05070d"]),
            border=ft.Border.only(bottom=ft.BorderSide(1, "#0f1c2b")),
        )

        # ------------------------------------------------------------- núcleo
        self.ring_far = ft.Container(
            width=286, height=286, border_radius=400, border=ft.Border.all(1, "#0d2b38")
        )
        self.ring_mid = ft.Container(
            width=214, height=214, border_radius=400, border=ft.Border.all(1, "#12485a")
        )
        self.ring_near = ft.Container(
            width=156, height=156, border_radius=400, border=ft.Border.all(2, ACCENT)
        )
        self.core = ft.Container(
            width=110,
            height=110,
            border_radius=400,
            gradient=ft.LinearGradient(
                begin=ft.Alignment.TOP_LEFT,
                end=ft.Alignment.BOTTOM_RIGHT,
                colors=["#0ea5e9", "#0b1b2b"],
            ),
            shadow=ft.BoxShadow(blur_radius=45, color=ACCENT, spread_radius=4),
            alignment=ft.Alignment.CENTER,
            content=ft.Icon(ft.Icons.GRAPHIC_EQ, color="#eafcff", size=34),
        )
        nucleo = ft.Container(
            width=300,
            height=300,
            content=ft.Stack(
                controls=[self.ring_far, self.ring_mid, self.ring_near, self.core],
                alignment=ft.Alignment.CENTER,
            ),
        )

        self.bars = [
            ft.Container(width=4, height=8, border_radius=2, bgcolor=ACCENT) for _ in range(28)
        ]
        onda = ft.Row(
            controls=self.bars,
            alignment=ft.MainAxisAlignment.CENTER,
            vertical_alignment=ft.CrossAxisAlignment.END,
            spacing=4,
            height=72,
        )

        # -------------------------------------------------- texto del diálogo
        self.user_text = ft.Text("", size=12, color="#5f7d8c", italic=True, text_align=ft.TextAlign.CENTER)
        self.answer_text = ft.Text(
            "Pulsa el micrófono o simplemente habla.",
            size=17,
            color="#dbeafe",
            text_align=ft.TextAlign.CENTER,
        )

        escenario = ft.Column(
            controls=[
                nucleo,
                onda,
                self.user_text,
                self.answer_text,
            ],
            spacing=14,
            alignment=ft.MainAxisAlignment.CENTER,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            expand=True,
        )
        principal = ft.Container(
            content=escenario,
            expand=True,
            padding=ft.Padding(left=28, top=10, right=28, bottom=10),
        )

        # ------------------------------------------------------ panel lateral
        self.metrics = ft.Text("", size=10, color="#5f7d8c", font_family="Consolas")
        self.hint = ft.Text(
            "Sin actividad todavía.",
            size=11,
            color="#3f5a68",
        )
        self.chat = ft.ListView(controls=[self.hint], expand=True, spacing=8, auto_scroll=True)
        lateral = ft.Container(
            width=310,
            content=ft.Column(
                controls=[
                    ft.Text("ACTIVIDAD", size=9, weight=ft.FontWeight.BOLD, color="#3f5a68"),
                    self.metrics,
                    ft.Container(height=1, bgcolor="#0f1c2b"),
                    self.chat,
                ],
                spacing=10,
            ),
            padding=18,
            bgcolor="#070c14",
            border=ft.Border.only(left=ft.BorderSide(1, "#0f1c2b")),
        )

        cuerpo = ft.Row(
            controls=[principal, lateral],
            spacing=0,
            expand=True,
            vertical_alignment=ft.CrossAxisAlignment.STRETCH,
        )

        # ------------------------------------------------------------- mandos
        self.mic_icon = ft.Icon(ft.Icons.MIC, size=26, color="#04121a")
        self.mic_ring = ft.Container(
            content=ft.Row(controls=[self.mic_icon], alignment=ft.MainAxisAlignment.CENTER),
            width=58,
            height=58,
            border_radius=29,
            gradient=ft.LinearGradient(colors=["#67e8f9", "#0ea5e9"]),
            shadow=ft.BoxShadow(blur_radius=22, color=ACCENT, spread_radius=2),
            on_click=self._on_mic_click,
        )
        self.mic_caption = ft.Text("Hablar", size=9, color="#4d6b7a")

        self.stop_button = ft.TextButton(content="Detener", icon=ft.Icons.STOP, on_click=self._on_stop_click, visible=False)
        self.clear_button = ft.TextButton(content="Limpiar", icon=ft.Icons.DELETE_OUTLINE, on_click=self._on_clear_click)
        self.hands_free_switch = ft.Switch(
            label="Manos libres",
            value=self.settings.hands_free,
            on_change=self._on_hands_free_change,
            scale=0.8,
        )

        entrada = (
            self.settings.input_device
            if self.settings.input_device is not None
            else default_input_index()
        )
        salida = (
            self.settings.output_device
            if self.settings.output_device is not None
            else default_output_index()
        )
        self.input_dd = ft.Dropdown(
            label="Micrófono",
            width=210,
            value=str(entrada) if entrada is not None else None,
            options=[ft.DropdownOption(key=str(d.index), text=d.label(26)) for d in input_devices()],
            on_select=self._on_input_device,
        )
        self.output_dd = ft.Dropdown(
            label="Salida",
            width=210,
            value=str(salida) if salida is not None else None,
            options=[ft.DropdownOption(key=str(d.index), text=d.label(26)) for d in output_devices()],
            on_select=self._on_output_device,
        )

        self.status = ft.Text("Conectando con Ollama…", size=10, color="#4d6b7a")

        pie = ft.Container(
            content=ft.Row(
                controls=[
                    ft.Column(
                        controls=[
                            ft.Row(controls=[self.mic_ring], alignment=ft.MainAxisAlignment.CENTER),
                            ft.Row(controls=[self.mic_caption], alignment=ft.MainAxisAlignment.CENTER),
                        ],
                        spacing=4,
                    ),
                    ft.Container(width=1, height=44, bgcolor="#0f1c2b"),
                    ft.Column(
                        controls=[
                            ft.Row(
                                controls=[self.hands_free_switch, self.stop_button, self.clear_button],
                                spacing=6,
                            ),
                            self.status,
                        ],
                        spacing=6,
                        expand=True,
                    ),
                    ft.Column(controls=[self.input_dd, self.output_dd], spacing=6),
                ],
                spacing=18,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.Padding(left=22, top=12, right=22, bottom=12),
            bgcolor="#070c14",
            border=ft.Border.only(top=ft.BorderSide(1, "#0f1c2b")),
        )

        page.add(
            ft.Column(
                controls=[cabecera, cuerpo, pie],
                spacing=0,
                expand=True,
            )
        )


    def _set_state(self, state: str, detail: str = "") -> None:
        self.state = state
        label = STATE_LABEL.get(state, state)
        self.state_label.value = label + ((" · " + detail) if detail else "")
        self.state_dot.bgcolor = STATE_COLOR.get(state, STATE_COLOR[IDLE])
        color = STATE_COLOR.get(state, ACCENT)
        self.ring_near.border = ft.Border.all(2, color)
        self.core.shadow = ft.BoxShadow(blur_radius=45, color=color, spread_radius=4)

        if state == LISTENING:
            caption = "Pausar" if self.settings.hands_free else "Detener"
            self.mic_icon.icon = ft.Icons.STOP
            self.mic_ring.bgcolor = DANGER
        elif state in (THINKING, SPEAKING):
            caption = "Interrumpir"
            self.mic_icon.icon = ft.Icons.STOP
            self.mic_ring.bgcolor = WARN
        else:
            caption = "Reanudar" if self.settings.hands_free else "Hablar"
            self.mic_icon.icon = ft.Icons.MIC
            self.mic_ring.bgcolor = ACCENT
        self.mic_caption.value = caption
        self.stop_button.visible = state in (THINKING, SPEAKING)
        # El micrófono NUNCA se deshabilita: siempre permite interrumpir o recuperar.
        self.page.update()

    def _add_bubble(self, role: str, text: str) -> ft.Text:
        is_user = role == "user"
        body = ft.Text(text, size=14, color=TEXT, selectable=True)
        avatar = ft.Container(
            content=ft.Icon(
                ft.Icons.PERSON if is_user else ft.Icons.SMART_TOY,
                size=16,
                color=TEXT if is_user else ACCENT,
            ),
            padding=6,
            border_radius=10,
            bgcolor=BUBBLE_USER if is_user else SURFACE_ALT,
        )
        bubble = ft.Container(
            content=ft.Column(
                controls=[
                    ft.Text(
                        "Tú" if is_user else "Asistente",
                        size=10,
                        color=MUTED,
                        weight=ft.FontWeight.W_600,
                    ),
                    body,
                ],
                spacing=4,
            ),
            padding=12,
            border_radius=14,
            bgcolor=BUBBLE_USER if is_user else BUBBLE_BOT,
            expand=True,
        )
        row = ft.Row(
            controls=[avatar, bubble] if not is_user else [bubble, avatar],
            spacing=8,
            vertical_alignment=ft.CrossAxisAlignment.START,
        )

        if not self._first_message_shown:
            self.chat.controls.clear()
            self._first_message_shown = True
        if role == "user":
            self.user_text.value = "«{}»".format(text)
            self.answer_text.value = ""
        elif role == "assistant":
            self.answer_text.value = text
        self.chat.controls.append(row)
        self.page.update()
        return body

    def _show_error(self, message: str) -> None:
        self.status.value = message
        self.status.color = DANGER
        self.page.update()

    def _show_info(self, message: str) -> None:
        self.status.value = message
        self.status.color = MUTED
        self.page.update()

    # -------------------------------------------------------------- arranque

    async def _startup(self) -> None:
        try:
            await asyncio.wait_for(self.client.ensure_model(), timeout=20.0)
        except (OllamaError, asyncio.TimeoutError) as exc:
            self._show_error(str(exc) or "Ollama no respondió a tiempo.")
            self._set_state(IDLE)
            self.mic_caption.value = "Sin conexión"
            self.page.update()
            return

        try:
            self.player.start()
        except Exception as exc:
            self._show_error("No se pudo abrir la salida de audio: {}".format(exc))

        # Un único bucle lee el micrófono de forma permanente: en manos libres
        # nunca se cierra el dispositivo, así no hay que pulsar nada.
        self._audio_task = asyncio.create_task(self._audio_loop())
        self._animate_task = asyncio.create_task(self._animate())

        await self._greet()

        if self.settings.hands_free:
            await self._start_listening()
        else:
            self._show_info("Pulsa el micrófono y habla.")
            self._set_state(IDLE)

    async def _greet(self) -> None:
        text = self.settings.greeting_text
        if not text:
            return
        self._add_bubble("assistant", text)
        self._set_state(SPEAKING, "saludo")
        try:
            wav = await asyncio.wait_for(self.client.synthesize(text), timeout=TTS_TIMEOUT)
            await self._play_wav(wav)
        except (OllamaError, asyncio.TimeoutError, Exception):
            pass
        self._set_state(IDLE)
        self._show_info("Te escucho cuando quieras.")

    # ------------------------------------------------------------- captura

    def _target_level(self) -> float:
        """Nivel 0..1 que alimenta la animación, según lo que esté pasando."""
        if self.state == LISTENING:
            raw = self._mic_level
        elif self.state in (THINKING, SPEAKING):
            raw = self.player.level
        else:
            raw = 0.0
        return max(0.0, min(1.0, raw / 3000.0))

    async def _animate(self) -> None:
        """Mueve el núcleo y las barras con el audio real, ~20 fps."""
        level = 0.0
        phase = 0.0
        while not self._closing:
            target = self._target_level()
            level = level * 0.80 + target * 0.20
            phase += 0.11
            for index, bar in enumerate(self.bars):
                wave = abs(math.sin(phase + index * 0.42))
                bar.height = 5.0 + (8.0 + level * 58.0) * (0.30 + 0.70 * wave)
            size = 104.0 + level * 28.0
            self.core.width = size
            self.core.height = size
            side = 214.0 + level * 26.0
            self.ring_mid.width = side
            self.ring_mid.height = side
            inner = 156.0 + level * 16.0
            self.ring_near.width = inner
            self.ring_near.height = inner
            self.ring_near.opacity = 0.45 + level * 0.55
            self.ring_far.opacity = 0.20 + level * 0.50
            try:
                self.page.update()
            except Exception:
                return
            await asyncio.sleep(0.05)

    def _align(self, chunk: bytes) -> bytes:
        """PCM16 necesita límites de 2 bytes; si un bloque llega impar se arrastra."""
        if self._odd_byte:
            chunk = self._odd_byte + chunk
            self._odd_byte = b""
        if len(chunk) % 2:
            self._odd_byte = chunk[-1:]
            chunk = chunk[:-1]
        return chunk

    async def _audio_loop(self) -> None:
        """Único consumidor del micrófono. Nunca se detiene mientras la app viva."""
        while not self._closing:
            if self.recorder.active:
                chunk = self.recorder.take()
                if chunk:
                    chunk = self._align(chunk)
                    if chunk:
                        try:
                            await self._route(chunk)
                        except Exception as exc:
                            self._show_error("Error de audio: {}".format(exc))
            await asyncio.sleep(0.05)

    async def _route(self, chunk: bytes) -> None:
        self._mic_level = rms(chunk)
        if self.state == LISTENING:
            if self.settings.hands_free:
                event = self.detector.feed(chunk)
                if event.kind == SPEECH_START:
                    self._show_info("Te escucho…")
                elif event.kind in (TURN_READY, OVERFLOW):
                    task = self._turn_task
                    if task is not None and not task.done():
                        return
                    self.pcm = bytearray(event.utterance)
                    self._turn_task = asyncio.create_task(self._finish_turn())
            else:
                # Modo pulsar para hablar: se acumula todo sin VAD.
                self.pcm.extend(chunk)
            return

        # Mientras piensa o habla: escuchar solo para detectar interrupción.
        if (
            self.settings.barge_in
            and self.settings.hands_free
            and self.state in (THINKING, SPEAKING)
        ):
            if self.barge.feed(chunk, self.detector.floor):
                self.barge.reset()
                self._pending = chunk
                self._stop_requested = True
                try:
                    self.player.clear()
                except Exception:
                    pass
                self._show_info("Te escucho…")

    async def _on_mic_click(self, event=None) -> None:
        if self.state == LISTENING:
            if self.settings.hands_free:
                await self._pause_listening()
            else:
                await self._finish_turn()
        elif self.state in (THINKING, SPEAKING):
            await self._stop_everything()
        else:
            await self._start_listening()

    async def _on_stop_click(self, event=None) -> None:
        await self._stop_everything()

    async def _on_clear_click(self, event=None) -> None:
        self.history.clear()
        self.chat.controls.clear()
        self.chat.controls.append(self.hint)
        self._first_message_shown = False
        self.metrics.value = ""
        self.user_text.value = ""
        self.answer_text.value = "Pulsa el micrófono o simplemente habla."
        self._show_info("Conversación reiniciada.")

    def _dropdown_value(self, event, control) -> int | None:
        raw = getattr(event, "data", None) if event is not None else None
        if raw in (None, ""):
            inner = getattr(event, "control", None) if event is not None else None
            raw = getattr(inner, "value", None)
        if raw in (None, ""):
            raw = getattr(control, "value", None)
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None

    async def _on_input_device(self, event=None) -> None:
        index = self._dropdown_value(event, self.input_dd)
        if index is None:
            return
        if self.state == LISTENING:
            await self._stop_recorder()
        self.settings = replace(self.settings, input_device=index)
        self.recorder = Recorder(device=index, rate=self.settings.sample_rate)
        self._show_info("Micrófono cambiado al dispositivo {}.".format(index))

    async def _on_output_device(self, event=None) -> None:
        index = self._dropdown_value(event, self.output_dd)
        if index is None:
            return
        try:
            self.player.stop()
        except Exception:
            pass
        self.settings = replace(self.settings, output_device=index)
        self.player = Player(device=index, rate=24000)
        self._show_info("Salida cambiada al dispositivo {}.".format(index))

    async def _on_hands_free_change(self, event=None) -> None:
        """Activa o desactiva la escucha permanente."""
        value = None
        if event is not None:
            data = getattr(event, "data", None)
            if isinstance(data, bool):
                value = data
            elif isinstance(data, str):
                value = data.strip().lower() in ("true", "1", "yes")
            if value is None:
                target = getattr(event, "target", None)
                target_value = getattr(target, "value", None)
                if isinstance(target_value, bool):
                    value = target_value
        if value is None:
            value = bool(self.hands_free_switch.value)
        self.hands_free_switch.value = value
        self.settings = replace(self.settings, hands_free=value)
        if value:
            await self._start_listening()
        else:
            await self._pause_listening()

    async def _start_listening(self, prefill: bytes = b"") -> None:
        self.pcm.clear()
        self._odd_byte = b""
        self.detector.reset()
        self.barge.reset()
        self._stop_requested = False
        if prefill:
            # Voz ya capturada durante la interrupción: sigue el mismo turno.
            self.detector.seed(prefill)

        try:
            self.player.start()
        except Exception:
            pass

        if not self.recorder.active:
            try:
                self.recorder.start()
            except Exception as exc:
                self._show_error("No se pudo abrir el micrófono: {}".format(exc))
                self._set_state(IDLE)
                return

        self._set_state(LISTENING)
        self._show_info(
            "Te escucho cuando quieras." if self.settings.hands_free else "Habla ahora."
        )

    async def _pause_listening(self) -> None:
        """Cierra el micrófono (manos libres en pausa)."""
        self.detector.reset()
        self.pcm.clear()
        try:
            self.recorder.stop()
        except Exception:
            pass
        self._set_state(IDLE)
        self._show_info("Micrófono en pausa. Pulsa para reanudar.")

    async def _stop_recorder(self) -> None:
        self.detector.reset()
        try:
            self.recorder.stop()
        except Exception:
            pass

    async def _finish_turn(self) -> None:
        if self.state != LISTENING:
            return
        self._set_state(THINKING, "transcribiendo")
        # En manos libres el micrófono se queda abierto: cerrarlo y reabrirlo
        # en cada turno añade cientos de milisegundos y pierde la primera sílaba.
        if not self.settings.hands_free:
            await self._stop_recorder()

        pcm = bytes(self.pcm)
        self._captured_seconds = len(pcm) / float(self.settings.bytes_per_second)
        self.pcm.clear()
        self.detector.reset()

        try:
            if len(pcm) < self.settings.min_turn_bytes:
                self._show_info("No se escuchó voz. Inténtalo otra vez.")
                return
            started = time.perf_counter()
            text = await asyncio.wait_for(self.client.transcribe(pcm), timeout=TRANSCRIBE_TIMEOUT)
            asr_seconds = time.perf_counter() - started
            if not text:
                self._show_info("No entendí el audio. Habla más cerca del micrófono.")
                return
            self._add_bubble("user", text)
            self._show_info("Generando respuesta…")
            await self._respond(text, asr_seconds)
        except asyncio.TimeoutError:
            self._show_error("La transcripción tardó demasiado. Se canceló el turno.")
        except OllamaError as exc:
            self._show_error(str(exc))
        except Exception as exc:
            self._show_error("Error inesperado en el turno: {}".format(exc))
        finally:
            # Red de seguridad: pase lo que pase, la UI vuelve a estar usable.
            self._stop_requested = True
            self._set_state(IDLE)
            if self.status.color != DANGER:
                self._show_info("Listo.")
            # Manos libres: se vuelve a escuchar sin que el usuario toque nada.
            if self.settings.hands_free and not self._closing:
                pending, self._pending = self._pending, b""
                await self._start_listening(prefill=pending)

    # ------------------------------------------------------------ respuesta

    def _messages_for(self, user_text: str) -> list[dict[str, str]]:
        limit = max(0, self.settings.history_turns) * 2
        history = self.history[-limit:] if limit else []
        return (
            [{"role": "system", "content": self.settings.system_text}]
            + list(history)
            + [{"role": "user", "content": user_text}]
        )

    async def _respond(self, user_text: str, asr_seconds: float) -> None:
        self._stop_requested = False
        self._timings = {}
        started = time.perf_counter()

        text_queue: asyncio.Queue = asyncio.Queue()
        wav_queue: asyncio.Queue = asyncio.Queue()
        bubble = self._add_bubble("assistant", "…")
        self.answer_text.value = ""
        self._set_state(SPEAKING, "respondiendo")

        result = {"answer": "", "error": ""}

        async def produce() -> None:
            """Decide si buscar, luego redacta con la personalidad.

            Son dos llamadas porque el modelo no puede a la vez seguir 18 reglas de
            estilo y emitir tool_calls: medido, en cuanto se le pide brevedad narra
            «busco noticias…» en lugar de llamar a la herramienta, y sin esa petición
            inventa las noticias. La llamada de decisión va sin prompt de personalidad
            y con salida acotada.
            """
            splitter = SentenceSplitter()
            collected = ""
            last_paint = 0.0
            mensajes = self._messages_for(user_text)
            try:
                llamadas: list = []
                if self.settings.web_search_enabled:
                    async for evento in self.client.stream_events(
                        [{"role": "user", "content": user_text}],
                        tools=TOOLS,
                        options={"temperature": 0.0, "num_predict": 96},
                    ):
                        if evento["type"] == "tool_calls":
                            llamadas = evento["calls"]
                    if llamadas:
                        self._show_info("Buscando en internet…")
                        # El aviso suena mientras se busca: se lanza en paralelo y se
                        # espera después, así no suma latencia al turno.
                        aviso = asyncio.create_task(self._announce("Buscando información."))
                        mensajes = mensajes + await _tool_messages(llamadas)
                        try:
                            await asyncio.wait_for(aviso, timeout=TTS_TIMEOUT)
                        except (OllamaError, asyncio.TimeoutError, Exception):
                            pass

                # Ollama devuelve vacío si el historial trae tool_calls y no se le
                # pasan las herramientas: hay que reenviarlas. Solo se permite una
                # ronda, así que los tool_calls de esta llamada se ignoran.
                async for evento in self.client.stream_events(
                    mensajes, tools=TOOLS if self.settings.web_search_enabled else None
                ):
                    if self._stop_requested:
                        break
                    if evento["type"] != "token":
                        continue
                    token = evento["text"]
                    collected += token
                    if not self._timings.get("first_token"):
                        self._timings["first_token"] = time.perf_counter() - started
                    now = time.perf_counter()
                    if now - last_paint > 0.08:
                        visible = to_speech_text(collected)
                        bubble.value = visible
                        self.answer_text.value = visible
                        self.page.update()
                        last_paint = now
                    for sentence in splitter.push(token):
                        await text_queue.put(sentence)
            except OllamaError as exc:
                result["error"] = str(exc)
            except Exception as exc:
                result["error"] = "Error generando la respuesta: {}".format(exc)
            finally:
                tail = splitter.flush()
                if tail:
                    await text_queue.put(tail)
                await text_queue.put(None)
                # Lo que se guarda y se muestra también va limpio: el historial
                # alimenta al modelo y la burbuja la lee el usuario.
                result["answer"] = to_speech_text(collected)
                bubble.value = result["answer"] or "(sin respuesta)"
                self.answer_text.value = result["answer"] or "(sin respuesta)"
                self.page.update()

        async def _tool_messages(llamadas: list) -> list:
            """Ejecuta las herramientas y devuelve los mensajes para el modelo."""
            salida: list = [{"role": "assistant", "content": "", "tool_calls": llamadas}]
            for llamada in llamadas:
                funcion = llamada.get("function") or {}
                nombre = funcion.get("name") or ""
                argumentos = funcion.get("arguments") or {}
                if isinstance(argumentos, str):
                    try:
                        argumentos = json.loads(argumentos)
                    except ValueError:
                        argumentos = {}
                resultado = await execute(nombre, argumentos)
                salida.append(
                    {"role": "tool", "content": resultado, "tool_name": nombre}
                )
            # El resultado invita a responder con listas; se recuerda el formato de voz.
            salida.append(
                {
                    "role": "system",
                    "content": "Responde en voz alta: una o dos frases, sin listas, "
                    "sin markdown y sin direcciones web. Si citas la fuente, nombra "
                    "el medio, nunca la URL.",
                }
            )
            return salida

        async def synthesize_worker() -> None:
            # El centinela va en finally: el reproductor nunca se queda esperando.
            try:
                while True:
                    sentence = await text_queue.get()
                    if sentence is None:
                        return
                    if self._stop_requested:
                        continue
                    # La voz nunca lee símbolos, aunque el modelo los escriba.
                    sentence = to_speech_text(sentence)
                    if not sentence:
                        continue
                    try:
                        wav = await asyncio.wait_for(
                            self.client.synthesize(sentence), timeout=TTS_TIMEOUT
                        )
                    except (OllamaError, asyncio.TimeoutError) as exc:
                        result["error"] = "Fallo de síntesis: {}".format(exc)
                        continue
                    if wav:
                        await wav_queue.put(wav)
            finally:
                await wav_queue.put(None)

        async def play_worker() -> None:
            while True:
                wav = await wav_queue.get()
                if wav is None:
                    return
                if self._stop_requested:
                    continue
                if not self._timings.get("first_audio"):
                    self._timings["first_audio"] = time.perf_counter() - started
                await self._play_wav(wav)

        tts_task = asyncio.create_task(synthesize_worker())
        play_task = asyncio.create_task(play_worker())

        try:
            await asyncio.wait_for(produce(), timeout=PRODUCE_TIMEOUT)
            await asyncio.wait_for(tts_task, timeout=TTS_TIMEOUT * 2)
            await asyncio.wait_for(play_task, timeout=600.0)
        except asyncio.TimeoutError:
            result["error"] = result["error"] or "La respuesta tardó demasiado y se canceló."
        except Exception as exc:
            result["error"] = result["error"] or "Error en el turno: {}".format(exc)
        finally:
            for task in (tts_task, play_task):
                if not task.done():
                    task.cancel()

        if result["answer"]:
            self.history.append({"role": "user", "content": user_text})
            self.history.append({"role": "assistant", "content": result["answer"]})
            keep = max(0, self.settings.history_turns) * 2
            if keep:
                self.history = self.history[-keep:]

        self._report_timings(asr_seconds, time.perf_counter() - started)
        if result["error"]:
            self._show_error(result["error"])


    async def _announce(self, texto: str) -> None:
        """Encola una frase corta sin esperar a que termine de sonar."""
        try:
            wav = await asyncio.wait_for(self.client.synthesize(texto), timeout=TTS_TIMEOUT)
        except (OllamaError, asyncio.TimeoutError, Exception):
            return
        pcm, rate, _canales = wav_to_pcm(wav)
        if not pcm or rate != self.player.rate:
            return
        try:
            self.player.enqueue(pcm)
        except Exception:
            pass

    async def _play_wav(self, wav: bytes) -> None:
        """Encola el PCM en el reproductor continuo y espera a que se vacíe.

        No hay widget ni evento que adivinar: el callback de PortAudio consume
        la cola muestra a muestra, así que las frases se encadenan sin cortes.
        """
        pcm, rate, _channels = wav_to_pcm(wav)
        if not pcm:
            return
        if rate != self.player.rate:
            # El modelo entrega 24 kHz; si algún día cambia, se avisa en vez de
            # reproducir a la velocidad equivocada.
            self._show_error(
                "El TTS devolvió {} Hz y el reproductor usa {} Hz.".format(rate, self.player.rate)
            )
            return
        duration = len(pcm) / float(rate * 2)
        self.player.enqueue(pcm)
        try:
            await asyncio.wait_for(
                asyncio.to_thread(self.player.wait_done, duration + 8.0),
                timeout=duration + 10.0,
            )
        except (asyncio.TimeoutError, Exception):
            pass

    def _report_timings(self, asr_seconds: float, total: float) -> None:
        self.metrics.value = (
            "audio {:.1f}s · ASR {:.2f}s · 1er token {:.2f}s · 1er audio {:.2f}s · total {:.2f}s".format(
                self._captured_seconds,
                asr_seconds,
                self._timings.get("first_token", 0.0),
                self._timings.get("first_audio", 0.0),
                total,
            )
        )
        self.page.update()

    async def _stop_everything(self) -> None:
        """Corta la respuesta en curso y deja el micrófono listo otra vez."""
        self._stop_requested = True
        try:
            self.player.clear()
        except Exception:
            pass
        self.pcm.clear()
        self.detector.reset()
        self.barge.reset()
        self._pending = b""
        self._set_state(IDLE)
        self._show_info("Detenido.")
        if self.settings.hands_free and not self._closing:
            await self._start_listening()

    async def shutdown(self) -> None:
        self._closing = True
        self._stop_requested = True
        for task in (self._audio_task, self._animate_task):
            if task is not None and not task.done():
                task.cancel()
        try:
            self.recorder.stop()
        except Exception:
            pass
        try:
            self.player.stop()
        except Exception:
            pass
        await self.client.aclose()


async def main(page: ft.Page) -> None:
    settings = load_settings()
    assistant = VoiceAssistant(page, settings)
    page.on_disconnect = lambda event=None: page.run_task(assistant.shutdown)


if __name__ == "__main__":
    ft.run(main)
