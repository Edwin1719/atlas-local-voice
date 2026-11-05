# Configuración

Todo se ajusta con variables de entorno. No hace falta tocar código ni crear
archivos de configuración.

## Servidor y modelo

| Variable | Defecto | Descripción |
|---|---|---|
| `VA_BASE_URL` | `http://127.0.0.1:11434` | Dirección de Ollama |
| `VA_MODEL` | `lfm3-omni:2b` | Debe declarar `audio` y `speech` |
| `VA_TIMEOUT` | `120` | Segundos de espera por petición |

## Identidad

| Variable | Defecto | Descripción |
|---|---|---|
| `VA_NAME` | `Atlas` | Nombre del asistente; alimenta saludo y personalidad |
| `VA_GREETING` | `Hola, me llamo {name}. ¿En qué puedo ayudarte?` | Saludo al abrir. Vacío = no saludar |
| `VA_SYSTEM_PROMPT` | (incluido) | Personalidad completa. `{name}` se sustituye |

## Voz

| Variable | Defecto | Descripción |
|---|---|---|
| `VA_VOICE` | `male-spanish` | `female-spanish`, `female-english`, `male-english` |
| `VA_TEMPERATURE` | `0.4` | Creatividad de las respuestas |

## Herramientas

| Variable | Defecto | Descripción |
|---|---|---|
| `VA_WEB_SEARCH` | `1` | `0` desactiva la búsqueda web y el tráfico a internet |

La búsqueda usa DuckDuckGo (HTML), sin clave de API. Cuando está activa, una
pregunta que dependa de hechos actuales hace dos llamadas al modelo (decidir y
redactar) y añade ~1,5 s al turno.

Voces disponibles según el servidor: `male`/`female` + idioma
(`spanish`, `english`, `portuguese`, `french`, `german`, `italian`, …).

> El endpoint de síntesis **no admite control de velocidad**: responde
> `only speed 1 is supported` a cualquier `speed` distinto de 1. El ritmo de la
> voz es el que da el modelo para esa voz.

## Diálogo continuo

| Variable | Defecto | Descripción |
|---|---|---|
| `VA_HANDS_FREE` | `1` | `0` = solo pulsar para hablar |
| `VA_BARGE_IN` | `1` | `0` = no se puede interrumpir hablando |
| `VA_BARGE_MULT` | `3.0` | Cuánto debe superar el ruido de fondo para interrumpir |
| `VA_BARGE_MIN_LEVEL` | `500` | Nivel mínimo absoluto para interrumpir |
| `VA_BARGE_SUSTAIN` | `0.35` | Segundos sostenidos para considerarlo interrupción |
| `VA_PREROLL` | `0.35` | Audio previo que se conserva al detectar voz |

## Detección de turno

| Variable | Defecto | Descripción |
|---|---|---|
| `VA_VAD_SILENCE` | `1.6` | Silencio que cierra el turno |
| `VA_VAD_MIN_SPEECH` | `0.5` | Voz mínima para considerar un turno |
| `VA_VAD_MAX_TURN` | `30.0` | Duración máxima de un turno (corte de seguridad) |

## Audio

| Variable | Defecto | Descripción |
|---|---|---|
| `VA_SAMPLE_RATE` | `16000` | Tasa de captura. No cambiar salvo problema del dispositivo |
| `VA_CHANNELS` | `1` | Canales de captura |
| `VA_INPUT_DEVICE` | (defecto del sistema) | Índice del micrófono |
| `VA_OUTPUT_DEVICE` | (defecto del sistema) | Índice de la salida |

Para conocer los índices, ejecuta la app y abre los desplegables del pie, o:

```powershell
python -c "import sounddevice as sd; print(sd.query_devices())"
```

## Conversación

| Variable | Defecto | Descripción |
|---|---|---|
| `VA_HISTORY_TURNS` | `8` | Turnos de memoria que se envían al modelo |

---

## Escenarios típicos

### Con altavoces (sin auriculares)

El micrófono capta el eco del altavoz. Súbelo para que no se interrumpa solo:

```powershell
$env:VA_BARGE_MIN_LEVEL="1200"
$env:VA_BARGE_MULT="4.0"
python run.py
```

### Sin interrupción

```powershell
$env:VA_BARGE_IN="0"
python run.py
```

### Modo pulsar para hablar

```powershell
$env:VA_HANDS_FREE="0"
python run.py
```

### Voz masculina y otro nombre

```powershell
$env:VA_VOICE="male-spanish"
$env:VA_NAME="Nova"
python run.py
```

### Habla pausada (corta a media frase)

```powershell
$env:VA_VAD_SILENCE="2.2"
$env:VA_VAD_MIN_SPEECH="0.4"
python run.py
```

### Personalidad propia

```powershell
$env:VA_SYSTEM_PROMPT="Eres Atlas, un asistente técnico. Respondes en dos frases, sin adornos y sin inventar."
python run.py
```

---

## Persistencia

No hay archivo de configuración ni base de datos. Las variables viven en la
sesión de la terminal. Para fijarlas de forma permanente en Windows:

```powershell
[Environment]::SetEnvironmentVariable("VA_VOICE", "male-spanish", "User")
```
