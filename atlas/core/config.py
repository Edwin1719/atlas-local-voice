"""Configuración del asistente de voz.

Cualquier valor se puede sobrescribir por variable de entorno con prefijo VA_,
sin tocar el código:

    set VA_VOICE=male-spanish
    set VA_VAD_THRESHOLD=900
    python app.py
"""
from __future__ import annotations

import os
from dataclasses import dataclass, replace

DEFAULT_NAME = "Atlas"

# El saludo es corto a propósito: cada palabra extra retrasa el primer audio.
DEFAULT_GREETING = "Hola, me llamo {name}. ¿En qué puedo ayudarte?"

# Personalidad y comportamiento. El nombre se sustituye en tiempo de ejecución.
DEFAULT_SYSTEM_PROMPT = (
    "Te llamas {name}. Eres un asistente de voz cercano, directo y competente.\n"
    "\n"
    "Cómo hablas:\n"
    "- Español neutro, tuteo, tono cálido y tranquilo.\n"
    "- Frases cortas: una o dos por respuesta, salvo que te pidan detalle.\n"
    "- Tu texto se convierte en voz: nunca uses listas, viñetas, markdown, "
    "emojis, asteriscos ni tablas.\n"
    "- Escribe los números, siglas y símbolos como se pronuncian.\n"
    "- No empieces con 'Claro', 'Por supuesto' ni repitiendo la pregunta.\n"
    "\n"
    "Cómo te comportas:\n"
    "- Si la petición es ambigua, haz una sola pregunta aclaratoria.\n"
    "- Si no sabes algo o no entendiste el audio, dilo sin rodeos.\n"
    "- No inventes datos, cifras, nombres ni fuentes.\n"
    "- Nunca respondas repitiendo la pregunta: aporta algo nuevo.\n"
    "- Para un cálculo, resuélvelo paso a paso y verifica el resultado; si no "
    "estás seguro, dilo en vez de dar una cifra.\n"
    "- En salud, dinero o temas legales, da información general y recomienda "
    "consultar a un profesional. Nunca des diagnósticos ni dosis.\n"
    "- Si te interrumpen, retoma donde ibas sin repetir todo.\n"
    "- Ofreces ayuda concreta, no genérica.\n"
    "- Si te piden algo que no puedes hacer, dilo y propone la alternativa más "
    "cercana que sí puedas."
)

VOICES = (
    "female-spanish",
    "male-spanish",
    "female-english",
    "male-english",
)


def _env_str(name: str, default: str) -> str:
    raw = os.getenv(name)
    return raw.strip() if raw and raw.strip() else default


def _env_type(name: str, default, cast):
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return cast(raw)
    except (TypeError, ValueError):
        return default


def _env_opt_int(name: str) -> int | None:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return None
    try:
        return int(raw.strip())
    except ValueError:
        return None


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "si", "sí", "on"}


@dataclass(frozen=True, slots=True)
class Settings:
    """Parámetros del asistente. Inmutable: se reemplaza con dataclasses.replace."""

    # --- Servidor ---
    base_url: str = "http://127.0.0.1:11434"
    model: str = "lfm3-omni:2b"
    voice: str = "male-spanish"
    temperature: float = 0.4
    request_timeout_s: float = 120.0

    # --- Captura ---
    sample_rate: int = 16000
    channels: int = 1
    input_device: int | None = None
    output_device: int | None = None

    # --- Diálogo continuo ---
    hands_free: bool = True
    barge_in: bool = True
    barge_mult: float = 3.0
    barge_min_level: float = 500.0
    barge_sustain_s: float = 0.35
    preroll_s: float = 0.35
    greeting: str = DEFAULT_GREETING

    # --- Detección de fin de turno ---
    vad_silence_s: float = 1.6
    vad_min_speech_s: float = 0.5
    vad_max_turn_s: float = 30.0

    # --- Herramientas ---
    web_search_enabled: bool = True

    # --- Identidad y conversación ---
    assistant_name: str = DEFAULT_NAME
    history_turns: int = 8
    system_prompt: str = DEFAULT_SYSTEM_PROMPT

    def _with_name(self, text: str) -> str:
        # replace en lugar de format: un prompt propio no debe romperse por llaves.
        return (text or "").replace("{name}", self.assistant_name)

    @property
    def greeting_text(self) -> str:
        return self._with_name(self.greeting).strip()

    @property
    def system_text(self) -> str:
        return self._with_name(self.system_prompt).strip()

    @property
    def bytes_per_second(self) -> int:
        """Bytes de PCM16 por segundo de audio."""
        return self.sample_rate * self.channels * 2

    @property
    def min_turn_bytes(self) -> int:
        """Mínimo de audio para considerar que hubo voz."""
        return int(self.bytes_per_second * self.vad_min_speech_s)


# Instancia con los valores por defecto. No se puede leer Settings.campo
# directamente porque con slots=True el acceso a la clase devuelve el descriptor.
_DEFAULTS = Settings()


def load_settings(**overrides) -> Settings:
    """Construye Settings leyendo el entorno y aplicando overrides explícitos."""
    base = Settings(
        base_url=_env_str("VA_BASE_URL", _DEFAULTS.base_url),
        model=_env_str("VA_MODEL", _DEFAULTS.model),
        voice=_env_str("VA_VOICE", _DEFAULTS.voice),
        temperature=_env_type("VA_TEMPERATURE", _DEFAULTS.temperature, float),
        request_timeout_s=_env_type("VA_TIMEOUT", _DEFAULTS.request_timeout_s, float),
        sample_rate=_env_type("VA_SAMPLE_RATE", _DEFAULTS.sample_rate, int),
        channels=_env_type("VA_CHANNELS", _DEFAULTS.channels, int),
        input_device=_env_opt_int("VA_INPUT_DEVICE"),
        output_device=_env_opt_int("VA_OUTPUT_DEVICE"),
        hands_free=_env_bool("VA_HANDS_FREE", _DEFAULTS.hands_free),
        barge_in=_env_bool("VA_BARGE_IN", _DEFAULTS.barge_in),
        barge_mult=_env_type("VA_BARGE_MULT", _DEFAULTS.barge_mult, float),
        barge_min_level=_env_type("VA_BARGE_MIN_LEVEL", _DEFAULTS.barge_min_level, float),
        barge_sustain_s=_env_type("VA_BARGE_SUSTAIN", _DEFAULTS.barge_sustain_s, float),
        preroll_s=_env_type("VA_PREROLL", _DEFAULTS.preroll_s, float),
        greeting=_env_str("VA_GREETING", _DEFAULTS.greeting),
        vad_silence_s=_env_type("VA_VAD_SILENCE", _DEFAULTS.vad_silence_s, float),
        vad_min_speech_s=_env_type("VA_VAD_MIN_SPEECH", _DEFAULTS.vad_min_speech_s, float),
        vad_max_turn_s=_env_type("VA_VAD_MAX_TURN", _DEFAULTS.vad_max_turn_s, float),
        web_search_enabled=_env_bool("VA_WEB_SEARCH", _DEFAULTS.web_search_enabled),
        assistant_name=_env_str("VA_NAME", _DEFAULTS.assistant_name),
        history_turns=_env_type("VA_HISTORY_TURNS", _DEFAULTS.history_turns, int),
        system_prompt=_env_str("VA_SYSTEM_PROMPT", _DEFAULTS.system_prompt),
    )
    if overrides:
        base = replace(base, **overrides)
    return base
