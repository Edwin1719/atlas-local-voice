# Atlas — asistente de voz local

[![Python](https://img.shields.io/badge/python-3.13-blue)]()
[![Pruebas](https://img.shields.io/badge/tests-87%20passing-brightgreen)]()
[![Runtime](https://img.shields.io/badge/runtime-Ollama-black)]()
[![Local](https://img.shields.io/badge/local--first-100%25-informational)]()
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

Asistente conversacional **voz a voz** que corre íntegramente en tu equipo:
escucha sin pulsar nada, responde hablando, busca noticias actuales y puede mirar
una imagen cuando se lo pides. Sin nube, sin claves de API y sin enviar tu audio a
terceros.

---

## Estado

| | |
|---|---|
| **Versión** | 0.13.1 |
| **Actualizado** | 2026-11-06 |
| **Python** | 3.13 (probado 3.13.18) |
| **Modelo** | `lfm3-omni:2b` (Q4_K_M, 1,73 B) |
| **Runtime** | Ollama ≥ 0.40.9 (probado 0.40.14) |
| **Interfaz** | Flet 1.1.0 |
| **Plataforma** | Windows (probado), Linux/macOS por PortAudio |

---

## Novedades de esta versión

| Versión | Cambio |
|---|---|
| **0.13.1** | Interfaz estable de dos columnas, reactor central, paleta de sala de control y **28 barras de frecuencia** que reaccionan a la voz. Se conserva la cámara. |
| **0.13** | Cámara bajo demanda: vista previa, botón «Mira esto» e imagen adjunta a la siguiente pregunta. |
| **0.12** | Tool calling según Ollama: acumulación de `tool_calls`, `content` y `thinking`; segunda ronda acotada; `num_predict=256`. |
| **0.11** | Noticias reales con Google News RSS; DuckDuckGo queda para búsquedas generales. |

> La interfaz anterior se mantiene como base. Se descartaron el HUD de tres
> columnas y el fondo tipo túnel porque recortaban el panel derecho o no alcanzaban
> la referencia visual; el reactor y la barra de frecuencia sí quedaron integrados.

---

## Características

- **Manos libres permanente.** El micrófono no se cierra entre turnos: hablas,
  responde y vuelve a escuchar.
- **Interrupción real.** Si hablas mientras responde, corta la voz y arranca un
  turno nuevo con lo que ya dijiste.
- **Detección de turno adaptativa.** Estima el ruido de fondo de la sala y conserva
  350 ms de pre-roll para no cortar la primera sílaba.
- **Reproducción continua.** El audio es una cola consumida por PortAudio; las
  frases se encadenan sin pausas artificiales.
- **Reactor y frecuencia reactivos.** El reactor central y las 28 barras se mueven
  con el nivel real de tu voz y con la voz del asistente.
- **Cámara bajo demanda.** Vista previa en el panel lateral y botón «Mira esto»:
  una instantánea se adjunta a la siguiente pregunta. Apagada por defecto, sin
  disco y solo contra tu Ollama local.
- **Búsqueda web.** Noticias con Google News RSS; consultas generales con
  DuckDuckGo. Sin clave de API.
- **Todo local.** Un solo modelo de 2 GB hace reconocimiento, razonamiento y voz.
  La búsqueda es la única salida a la red y se puede desactivar.

---

## Interfaz

La app usa una estructura de **dos columnas**:

```
┌──────────────────────────────────────────────┬────────────────────┐
│ REACTOR + 28 BARRAS DE FRECUENCIA            │ ACTIVIDAD          │
│ estado, transcripción y respuesta            │ chat + métricas    │
│                                              │ SENSOR VISUAL      │
├──────────────────────────────────────────────┴────────────────────┤
│ COMMAND DECK: micrófono, manos libres, detener, limpiar, dispositivos │
└─────────────────────────────────────────────────────────────────────┘
```

- **Reactor central** (`atlas/ui/reactor.py`): anillos, arcos, partículas y núcleo
  dibujados con `flet.canvas`. Cambia de color según el estado.
- **Barra de frecuencia**: 28 barras debajo del reactor. Suben y bajan con el nivel
  del micrófono mientras escuchas y con el audio de salida mientras habla.
- **Panel de actividad**: conversación, métricas y tarjeta de cámara cuando está
  encendida.
- **Command deck**: pausa/reanudar, manos libres, detener, limpiar, micrófono y
  salida.
- **Ventana**: 1585×895 por defecto. Si tu pantalla es más pequeña, maximízala; el
  diseño está pensado para ese ancho.

---

## Arquitectura

### Vista por capas

```
┌────────────────────────────────────────────────────────────────────────┐
│ ENTRADA                                                                │
│ PortAudio InputStream  ─►  buffer (threading.Lock)                     │
│ el hilo solo acumula; no toca asyncio                                  │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   │ PCM16 · 16 kHz
┌──────────────────────────────────▼─────────────────────────────────────┐
│ DECISIÓN                                                               │
│ ContinuousDetector  suelo adaptativo + pre-roll 350 ms                 │
│ BargeMonitor        solo en thinking/speaking                          │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   │ turno cerrado
┌──────────────────────────────────▼─────────────────────────────────────┐
│ MODELO · Ollama 127.0.0.1:11434                                        │
│ 1  POST /v1/chat/completions  input_audio  → texto                     │
│ 2  POST /api/chat             stream      → tokens / tool_calls        │
│ 3  POST /v1/audio/speech      por frase   → WAV 24 kHz                 │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   │ WAV → PCM
┌──────────────────────────────────▼─────────────────────────────────────┐
│ SALIDA                                                                 │
│ Player: cola thread-safe ─► callback ─► tarjeta                        │
│ sin sleep, sin eventos, sin cortes                                     │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   │ RMS del bloque
                                   ▼
                    reactor + 28 barras + vista previa de cámara
```

### Máquina de estados

```
   ● listening ── 1,6 s de silencio ──► ● thinking ── primer token ──► ● speaking
   ▲                                                                            │
   └─────────────────────── fin del turno (manos libres) ───────────────────────┘

   ● idle     pausa manual o Detener, desde cualquier estado
```

### Un turno, en el tiempo

```
  tú hablas        Atlas escucha          Atlas piensa        Atlas responde
      │                  │                      │                    │
      ├── voz ──────────►│                      │                    │
      │            1,6 s de silencio            │                    │
      │                  ├── ASR ──────────────►│                    │
      │                  │                      ├── LLM (stream) ───►│
      │                  │                      │   frase 1 ────────►│ TTS
      │                  │                      │                    ├── suena
      │                  │                      │   frase 2 ────────►│ TTS
      │                  │                      │                    ├── suena
      │◄───────────────── vuelve a escuchar ───┴────────────────────┤
```

La síntesis de la frase **N+1** ocurre mientras suena la **N**: el primer audio no
espera a que el modelo termine de responder.

### Módulos

| Módulo | Responsabilidad | No hace |
|---|---|---|
| `app.py` | Interfaz, máquina de estados, orquestación, reactor y barras | No accede a dispositivos ni a la red |
| `audio/io.py` | Abrir dispositivos, capturar y reproducir | No conoce el modelo ni el diálogo |
| `audio/dialog.py` | Decidir cuándo empieza y termina un turno; detectar interrupciones | No toca audio ni red |
| `llm/client.py` | ASR, chat, TTS y tool calling | No conoce estados ni UI |
| `core/audio_utils.py` | Conversión PCM ↔ WAV | Sin estado |
| `core/config.py` | Configuración tipada e inmutable | Sin efectos secundarios |
| `core/text_utils.py` | Limpieza de markdown para voz y pantalla | Sin estado |
| `tools.py` | `buscar_web`: Google News RSS + DuckDuckGo | No conoce la UI |
| `vision/camera.py` | Captura OpenCV, vista previa y snapshot | No envía nada a la red |
| `ui/reactor.py` | Formas del reactor para `flet.canvas` | No conoce voz ni cámara |

La regla: **solo `app.py` conoce el orden de las cosas**. Los demás módulos se
prueban por separado, y así se validaron el detector, el cliente, la cámara y el
reactor antes de integrarlos.

### Concurrencia

Tres tareas asíncronas y dos hilos de PortAudio:

| Tarea / hilo | Frecuencia | Qué hace |
|---|---|---|
| callback de entrada | ~40 bloques/s | Acumula bytes en un buffer con lock |
| callback de salida | ~21 ms | Consume la cola y escribe la tarjeta |
| `_audio_loop()` | 50 ms | Toma el buffer y lo enruta según el estado |
| `_animate()` | 50 ms | Actualiza reactor, 28 barras y vista previa de cámara |
| tarea del turno | por turno | Transcribe → responde → sintetiza → reproduce |

**Por qué un solo bucle de audio.** Con dos (uno para escuchar y otro para detectar
interrupciones) ambos consumen el mismo buffer y se pisan. Un único consumidor con
un `if` por estado elimina esa clase de error.

**Por qué no se usan callbacks de asyncio desde PortAudio.** El callback corre en un
hilo del sistema; llamar a `loop.call_soon_threadsafe` en cada bloque introduce
contención y errores al cerrar el dispositivo. El hilo solo escribe en un buffer con
`threading.Lock` y el bucle asíncrono lo lee.

### Detección de turno

`ContinuousDetector` tiene dos estados: `idle` y `speech`.

```
floor  = 0.95 · floor + 0.05 · nivel      (solo en idle, nunca durante el turno)
disparo = max(floor × 3.0, 200)
```

- **Inicio:** dos bloques consecutivos por encima del disparo (200 ms). Un golpe
  aislado no abre un turno.
- **Fin:** 1,6 s de silencio y al menos 0,5 s de voz acumulada.
- **Pre-roll:** los 350 ms anteriores al disparo se añaden al turno, así la primera
  sílaba nunca se pierde.
- **Corte de seguridad:** 30 s por turno.

El suelo se actualiza **solo cuando no hay voz**. Si se actualizara siempre, el
propio turno subiría el suelo y el detector se cerraría a sí mismo.

### Interrupción

`BargeMonitor` actúa solo en `thinking` y `speaking`, y exige `max(floor × 3, 500)`
**sostenido 350 ms**. Un pico suelto no interrumpe; el eco constante del altavoz
tampoco. Al dispararse: vacía la cola, marca el corte y guarda ese audio para
empezar el siguiente turno con él.

### Reproducción sin cortes

El TTS entrega un WAV por frase; se extrae el PCM y se encola. El callback de salida
lo consume muestra a muestra: no hay `sleep` adivinando duraciones ni eventos que
esperar.

> **Trampa documentada.** El WAV de Ollama trae una cabecera con tamaño de datos
> falso —se midieron 89.478 s para un clip de 0,5 s—. La duración se calcula con los
> bytes realmente recibidos, nunca con `wave.getnframes()`.

---

## Requisitos

1. **Python 3.13** (sirve cualquier versión ≥ 3.11).
2. **Ollama ≥ 0.40.9** en marcha, con el modelo instalado:

```powershell
ollama list
ollama show lfm3-omni:2b
```

La salida debe incluir `audio` y `speech` entre las capacidades; para la cámara,
también `vision`.

## Instalación y ejecución

### 1. Crear el entorno

Desde la carpeta del proyecto:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

O con conda:

```powershell
conda create -n atlas python=3.13 -y
conda activate atlas
```

Comprueba el intérprete:

```powershell
python -c "import sys; print(sys.version, sys.executable)"
```

### 2. Instalar dependencias

```powershell
python -m pip install --only-binary=:all: -r requirements.txt
```

La cámara usa `opencv-python-headless`, incluido en `requirements.txt`. Si no se
instala, el asistente funciona igual y la cámara muestra un aviso.

### 3. Ejecutar

```powershell
python run.py
```

Al abrir, Atlas saluda por voz y se queda escuchando. La primera carga del modelo
puede tardar unos segundos; después el turno en caliente baja a ~1 s.

> `app.py` es un módulo del paquete, no un script suelto. Se lanza con
> `python run.py` o `python -m atlas.app`; `python atlas/app.py` fallaría por las
> rutas de importación.

---

## Uso

| Control | Acción |
|---|---|
| Botón circular | Pausa o reanuda el micrófono |
| **Manos libres** | Escucha permanente (activado por defecto) |
| **Detener** | Corta la respuesta y vuelve a escuchar |
| **Limpiar** | Reinicia la conversación |
| **Micrófono / Salida** | Elige dispositivo de audio |
| **Icono de cámara** | Enciende o apaga la vista previa; «Mira esto» adjunta una instantánea a la próxima pregunta |

Habla con naturalidad: el reactor y las 28 barras reaccionan al nivel de tu voz. Si
preguntas por noticias o hechos actuales, verás «Buscando información» y la respuesta
llegará con los datos encontrados.

> **Cámara.** La imagen se envía solo a tu Ollama local, se consume una vez y no se
> guarda en disco. El modelo describe objetos y escenas; el OCR de texto pequeño no
> es fiable. Ver [docs/CAMERA.md](docs/CAMERA.md).

> **Usa auriculares si puedes.** Con altavoces, el micrófono oye al propio asistente
> y puede interrumpirse a sí mismo. Ver
> [solución de problemas](docs/TROUBLESHOOTING.md).

---

## Cámara bajo demanda

- **Requisito:** `opencv-python-headless==5.0.0.93` (incluido).
- **Flujo:** icono de cámara → vista previa en el panel lateral → **Mira esto** →
  la instantánea se adjunta a la siguiente pregunta y se descarta.
- **Privacidad:** la imagen va como `images` en base64 a tu Ollama local; no se
  escribe en disco ni se envía a ningún servicio externo.
- **Límite honesto:** son instantáneas, no vídeo en tiempo real. El OCR de texto
  pequeño puede fallar con un modelo de 1,73 B.

Configuración: `VA_CAMERA_INDEX`, `VA_CAMERA_WIDTH`, `VA_CAMERA_HEIGHT` y
`VA_CAMERA_PREVIEW_FPS`. Diseño completo en [docs/CAMERA.md](docs/CAMERA.md).

---

## Rendimiento medido

| Etapa | Latencia |
|---|---|
| Transcripción de 5 s de audio | 0,48 – 0,72 s |
| Primer token de respuesta | 0,06 – 0,14 s |
| Primer audio sintetizado | 0,42 – 0,68 s |
| Turno completo en caliente | 0,8 – 1,5 s |
| Primer turno (modelo en frío) | ~4,5 s |
| Visión de una imagen (caliente) | 0,43 – 0,95 s |
| Primera imagen (modelo en frío) | ~4 s |
| Saludo inicial (3,5 s de voz) | 1,22 s de síntesis |

---

## Estructura

```
.
├── run.py                     punto de entrada: python run.py
├── README.md                  este archivo
├── requirements.txt           dependencias con versiones fijas
├── .gitignore
├── atlas/                     paquete de la aplicación
│   ├── __init__.py
│   ├── app.py                 interfaz, estados y orquestación
│   ├── core/
│   │   ├── config.py          configuración tipada por entorno
│   │   ├── audio_utils.py     conversión PCM ↔ WAV
│   │   └── text_utils.py      limpieza de markdown para voz
│   ├── audio/
│   │   ├── io.py              captura y reproducción (PortAudio)
│   │   └── dialog.py          detección de turno e interrupción
│   ├── llm/
│   │   └── client.py          cliente HTTP (ASR, chat, TTS)
│   ├── vision/
│   │   └── camera.py          captura OpenCV, preview y snapshot
│   ├── ui/
│   │   └── reactor.py         reactor de flet.canvas
│   └── tools.py               buscar_web (Google News + DuckDuckGo)
├── tests/
│   ├── test_audio_utils.py
│   ├── test_camera.py
│   ├── test_config.py
│   ├── test_dialog.py
│   ├── test_pipeline.py
│   ├── test_text_utils.py
│   └── test_tools.py
└── docs/
    ├── CONFIGURATION.md       todas las variables de entorno
    ├── TROUBLESHOOTING.md     síntomas y soluciones
    ├── DECISIONS.md           decisiones de diseño y por qué
    ├── CAMERA.md              diseño e implementación de la cámara
    ├── MCP.md                 propuesta de integración de MCP
    └── CHANGELOG.md           historial de versiones
```

El proyecto es autónomo: no depende de archivos externos, rutas absolutas ni del
repositorio del que nació. Solo necesita Ollama, Python y los controladores de
audio del sistema.

---

## Pruebas

```powershell
python -m unittest discover -s tests -t .
```

87 pruebas, sin dependencias extra: `unittest` es parte de la biblioteca estándar.
El flujo completo se prueba con dobles de página, micrófono y altavoz, así que la
batería corre sin hardware y sin red.

| Archivo | Qué cubre |
|---|---|
| `test_audio_utils.py` | Conversión WAV ↔ PCM y cabeceras con tamaño falso |
| `test_camera.py` | Captura, preview, snapshot y ausencia de OpenCV |
| `test_config.py` | Valores por defecto, entorno, identidad e inmutabilidad |
| `test_dialog.py` | Detección de turno, ruido de fondo, interrupción |
| `test_pipeline.py` | Saludo, turno completo, vuelta a escuchar, detener y UI de cámara |
| `test_text_utils.py` | Limpieza de markdown, emojis, tablas y puntuación |
| `test_tools.py` | Parser de DuckDuckGo, Google News y límites de red |

---

## Configuración rápida

```powershell
$env:VA_VOICE="female-spanish"
$env:VA_NAME="Nova"
$env:VA_BARGE_IN="0"
python run.py
```

Lista completa en [docs/CONFIGURATION.md](docs/CONFIGURATION.md).

---

## Herramientas y noticias

`buscar_web` se activa cuando la pregunta depende de hechos actuales:

1. **llamada de decisión** sin personalidad, salida acotada;
2. si hay `tool_calls`, se ejecuta `buscar_web`;
3. **llamada de redacción** con los resultados;
4. si el modelo pide otra búsqueda, se permite **una ronda más**.

Los `tool_calls`, `content` y `thinking` se acumulan de todos los fragmentos del
stream; el mensaje del asistente se reconstruye con los tres campos y se vuelven a
pasar las herramientas en la llamada final. Para noticias se usa **Google News
RSS** (titulares reales, sin clave); para el resto, **DuckDuckGo HTML**. Se
devuelven tres titulares como máximo y sin URLs para que la voz no lea direcciones.
El detalle está en [docs/DECISIONS.md](docs/DECISIONS.md).

---

## Limitaciones conocidas

Estas son reales y medidas, no advertencias genéricas:

1. **El modelo es el techo del reconocimiento.** Un modelo de 1,73 B en Q4 no
   compite con un ASR dedicado.
2. **Aritmética poco fiable.** Puede responder `1250 × 4 = 312.5`.
3. **Eco con altavoces.** La interrupción requiere auriculares o subir
   `VA_BARGE_MIN_LEVEL`.
4. **Bluetooth añade latencia** de 150–300 ms y cortes ocasionales.
5. **Un solo usuario.** No hay multiplexación ni sesiones concurrentes.
6. **OCR flojo en la cámara.** El modelo describe objetos, colores y escenas, pero
   puede leer mal un «ERROR 404» o una ruta. Para texto fiable hace falta OCR o un
   modelo mayor.
7. **La interfaz no es un HUD de tres columnas.** Se priorizó una app estable de dos
   columnas; el reactor y la barra de frecuencia son la mejora visual.

---

## Hoja de ruta

### Implementado

- **Herramientas y noticias:** `buscar_web` con Google News RSS y DuckDuckGo.
- **Cámara bajo demanda:** vista previa, snapshot y envío con la siguiente pregunta.
- **Interfaz:** reactor central, paleta de sala de control y 28 barras de frecuencia.
- **Tool calling:** acumulación de stream, segunda ronda y `num_predict=256`.

### Pendiente, con viabilidad comprobada

| Propuesta | Aporte | Dependencia |
|---|---|---|
| Ajustes en pantalla | Dejar de exigir variables de entorno | — |
| Carga de texto y voz | Leer archivos y transcribir audio | `ffmpeg` para MP3 |
| Más herramientas | Hora, fecha, calculadora, archivos | — |
| Navegación por secciones | Escalar cuando crezca la app | Ajustes y archivos |
| Servidores MCP | Reutilizar integraciones existentes | [Propuesta](docs/MCP.md) |
| Vídeo por muestreo | Resumen de vídeo, no tiempo real | `ffmpeg` u OpenCV |

**Lo que no recomiendo:** muchas herramientas a la vez con este modelo (falla al
elegir) y vender vídeo continuo como si fuera nativo. Instantáneas sí; flujo
continuo no.

---

## Licencia

Código bajo **MIT**: puedes usarlo, modificarlo, distribuirlo y venderlo, siempre
que conserves el aviso de autoría. Ver [LICENSE](LICENSE).

El **modelo** es independiente del código y tiene su propia licencia
([LFM-1.0](https://huggingface.co/LiquidAI/LFM3-Omni-2B)). Esta licencia cubre
lo que hay en este repositorio, no los pesos ni los servicios de terceros que
consume.

---

## Créditos

- Modelo [LFM3-Omni-2B](https://huggingface.co/LiquidAI/LFM3-Omni-2B) de Liquid AI
  (licencia LFM-1.0).
- Interfaz con [Flet](https://flet.dev); audio con PortAudio vía `sounddevice`.
- Reactor y animación: `flet.canvas` sobre el nivel de audio real.
