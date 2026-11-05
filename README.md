# Atlas — asistente de voz local

[![Python](https://img.shields.io/badge/python-3.13-blue)]()
[![Pruebas](https://img.shields.io/badge/tests-63%20passing-brightgreen)]()
[![Runtime](https://img.shields.io/badge/runtime-Ollama-black)]()
[![Local](https://img.shields.io/badge/local--first-100%25-informational)]()
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

Asistente conversacional **voz a voz** que corre íntegramente en tu equipo:
escucha sin pulsar nada, responde hablando y busca en internet cuando hace falta.
Sin nube, sin claves de API, sin enviar tu audio a terceros.

---

## Estado

| | |
|---|---|
| **Versión** | 0.4 |
| **Python** | 3.13 (probado 3.13.18) |
| **Modelo** | `lfm3-omni:2b` (Q4_K_M, 1,73 B) |
| **Runtime** | Ollama ≥ 0.40.9 (probado 0.40.14) |
| **Plataforma** | Windows (probado), Linux/macOS por PortAudio |

---

## Características

- **Manos libres permanente.** El micrófono nunca se cierra entre turnos: no hay
  botón que pulsar. Hablas, responde, vuelve a escuchar.
- **Interrupción real.** Si hablas mientras responde, corta la voz y arranca un
  turno nuevo con lo que ya dijiste.
- **Detección de turno adaptativa.** Estima el ruido de fondo de la sala en lugar
  de usar un umbral fijo, y conserva 350 ms de pre-roll para no cortar la primera
  sílaba.
- **Reproducción continua.** El audio es una cola consumida por PortAudio; las
  frases se encadenan sin cortes ni pausas artificiales.
- **Núcleo reactivo.** La interfaz se mueve con el nivel de audio real: tu voz
  mientras escucha, la del asistente mientras habla.
- **Respuestas limpias.** El texto se limpia de markdown, emojis, tablas y enlaces
  antes de mostrarse, guardarse y sintetizarse. No depende del prompt: es código.
- **Búsqueda web.** Cuando la pregunta depende de hechos actuales, busca en internet
  y responde con lo encontrado. Sin clave de API.
- **Todo local.** Un solo modelo de 2 GB hace reconocimiento, razonamiento y voz
  (la búsqueda es la única salida a la red, y se puede desactivar).

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
│ 2  POST /api/chat             stream      → tokens                     │
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
                      núcleo y 28 barras de la UI
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
| `app.py` | Interfaz, máquina de estados, orquestación, animación | No accede a dispositivos ni a la red |
| `audio_io.py` | Abrir dispositivos, capturar y reproducir | No conoce el modelo ni el diálogo |
| `dialog.py` | Decidir cuándo empieza y termina un turno; detectar interrupciones | No toca audio ni red |
| `ollama_client.py` | Las tres llamadas HTTP | No conoce estados ni UI |
| `audio_utils.py` | Conversión PCM ↔ WAV | Sin estado |
| `config.py` | Configuración tipada e inmutable | Sin efectos secundarios |

La regla: **solo `app.py` conoce el orden de las cosas**. Los demás módulos se
prueban por separado, y así se validaron el detector, el cliente y el reproductor
antes de integrarlos.

### Concurrencia

Tres tareas asíncronas y dos hilos de PortAudio:

| Tarea / hilo | Frecuencia | Qué hace |
|---|---|---|
| callback de entrada | ~40 bloques/s | Acumula bytes en un buffer con lock |
| callback de salida | ~21 ms | Consume la cola y escribe la tarjeta |
| `_audio_loop()` | 50 ms | Toma el buffer y lo enruta según el estado |
| `_animate()` | 50 ms | Actualiza núcleo y barras |
| tarea del turno | por turno | Transcribe → responde → sintetiza → reproduce |

**Por qué un solo bucle de audio.** Con dos (uno para escuchar y otro para
detectar interrupciones) ambos consumen el mismo buffer y se pisan. Un único
consumidor con un `if` por estado elimina esa clase de error.

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
esperar (ese fue el error que cortaba las frases en la primera versión).

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

La salida debe incluir `audio` y `speech` entre las capacidades.

## Instalación y ejecución

### 1. Crear el entorno

Desde la carpeta del proyecto. Usa el nombre que quieras.

**Con venv** (viene con Python, no requiere nada extra):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

**Con conda** (si lo prefieres):

```powershell
conda create -n atlas python=3.13 -y
conda activate atlas
```

Comprueba que el intérprete es el correcto antes de seguir:

```powershell
python -c "import sys; print(sys.version, sys.executable)"
```

### 2. Instalar dependencias

```powershell
python -m pip install --only-binary=:all: -r requirements.txt
```

### 3. Ejecutar

```powershell
python run.py
```

Al abrir, Atlas saluda por voz y se queda escuchando.

**Sobre `app.py`.** Es el módulo de la aplicación, no un script suelto: usa rutas
del paquete (`from atlas.core...`), así que `python atlas/app.py` fallaría. Se
lanza por cualquiera de estas dos vías equivalentes:

| Comando | Cuándo usarlo |
|---|---|
| `python run.py` | Lo normal. Funciona incluso desde otra carpeta |
| `python -m atlas.app` | Si prefieres invocar el módulo directamente |

---

## Uso

| Control | Acción |
|---|---|
| Botón circular | Pausa o reanuda el micrófono |
| **Manos libres** | Escucha permanente (activado por defecto) |
| **Detener** | Corta la respuesta y vuelve a escuchar |
| **Limpiar** | Reinicia la conversación |
| **Micrófono / Salida** | Elige dispositivo de audio |

> **Usa auriculares si puedes.** Con altavoces, el micrófono oye al propio
> asistente y puede interrumpirse a sí mismo. Ver
> [solución de problemas](docs/TROUBLESHOOTING.md).

---

## Rendimiento medido

| Etapa | Latencia |
|---|---|
| Transcripción de 5 s de audio | 0,48 – 0,72 s |
| Primer token de respuesta | 0,06 – 0,14 s |
| Primer audio sintetizado | 0,42 – 0,68 s |
| Turno completo en caliente | 0,8 – 1,5 s |
| Primer turno (modelo en frío) | ~4,5 s |
| Saludo inicial (3,5 s de voz) | 1,22 s de síntesis |

---

## Estructura

La carpeta `asistente_voz/` **es** el proyecto: se puede copiar o mover tal cual.

```
.
├── run.py                 punto de entrada: python run.py
├── README.md              este archivo: arquitectura, uso y configuración
├── requirements.txt       dependencias con versiones fijas
├── .gitignore
├── atlas/                 paquete de la aplicación
│   ├── __init__.py
│   ├── app.py             interfaz, estados y orquestación
│   ├── core/
│   │   ├── config.py      configuración tipada por entorno
│   │   └── audio_utils.py conversión PCM ↔ WAV
│   ├── audio/
│   │   ├── io.py          captura y reproducción (PortAudio)
│   │   └── dialog.py      detección de turno e interrupción
│   └── llm/
│       └── client.py      cliente HTTP (ASR, LLM, TTS)
├── tests/                 pruebas de funcionalidad
│   ├── test_audio_utils.py
│   ├── test_config.py
│   ├── test_dialog.py
│   └── test_pipeline.py
└── docs/
    ├── CONFIGURATION.md   todas las variables de entorno
    ├── TROUBLESHOOTING.md síntomas y soluciones
    ├── DECISIONS.md       decisiones de diseño y por qué
    └── CHANGELOG.md       historial de versiones
```

El proyecto es autónomo: no depende de archivos externos, rutas absolutas ni del
repositorio del que nació. Solo necesita Ollama, Python y los controladores de
audio del sistema.

---

## Pruebas

```powershell
python -m unittest discover -s tests -t .
```

35 pruebas, sin dependencias extra: `unittest` es parte de la biblioteca estándar.
El flujo completo se prueba con dobles de página, micrófono y altavoz, así que la
batería corre sin hardware y sin red.

| Archivo | Qué cubre |
|---|---|
| `test_audio_utils.py` | Conversión WAV ↔ PCM y cabeceras con tamaño falso |
| `test_config.py` | Valores por defecto, entorno, identidad e inmutabilidad |
| `test_dialog.py` | Detección de turno, ruido de fondo, interrupción |
| `test_pipeline.py` | Saludo, turno completo, vuelta a escuchar, detener |

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

## Limitaciones conocidas

Estas son reales y medidas, no advertencias genéricas:

1. **El modelo es el techo del reconocimiento.** Un ómnibus de 1,73 B en Q4 no
   compite con un ASR dedicado. Si el dato `audio` del pie coincide con lo que
   hablaste y aun así falla la transcripción, el límite es el modelo.
2. **Aritmética poco fiable.** Puede responder `1250 × 4 = 312.5`. No es un problema
   del prompt: es el tamaño del modelo.
3. **Eco con altavoces.** La interrupción requiere auriculares o subir
   `VA_BARGE_MIN_LEVEL`.
4. **Bluetooth añade latencia** de 150–300 ms y cortes ocasionales.
5. **Un solo usuario.** No hay multiplexación ni sesiones concurrentes.

---

## Hoja de ruta

> **Nada de esta sección está implementado.** Son propuestas con su viabilidad ya
> comprobada contra el modelo y el servidor actuales, para no planificar sobre
> suposiciones.

### Qué se verificó antes de proponerlo

| Capacidad | Estado | Evidencia |
|---|---|---|
| Herramientas (*tool calling*) | **Implementado** | `buscar_web` en producción; ver *Herramientas* |
| Visión (imágenes) | **Funciona** | Describió correctamente una imagen de prueba (fondo rojo, círculo azul) |
| Vídeo nativo | **No existe** | El modelo no acepta vídeo; hay que muestrear fotogramas |
| Control de velocidad de voz | **No disponible** | El servidor responde `only speed 1 is supported` |
| MCP | **Del lado del cliente** | El modelo solo ve herramientas; el protocolo lo pone nuestra app |

---

### 1. Herramientas — `buscar_web` ya implementada

**Qué hace.** Cuando la conversación depende de hechos actuales (noticias, precios,
clima), el asistente **anuncia por voz «Buscando información»**, busca en internet y
resume el resultado en una o dos frases, sin leer la lista de enlaces. El aviso suena
mientras se ejecuta la búsqueda, así que no añade espera.

**Cómo está montado**, con una sola herramienta a propósito:

```
1. llamada de decisión  (sin personalidad, salida acotada)
        └─► ¿tool_calls? ──► buscar_web ──► resultados como texto
2. llamada de redacción (personalidad completa + resultados)
```

Son dos llamadas porque el modelo no puede a la vez seguir las reglas de estilo y
emitir `tool_calls`: **medido**, en cuanto se le pide brevedad contesta «busco
noticias…» en lugar de llamar, y sin esa petición inventa las noticias. La decisión
va sin prompt de personalidad; la redacción con él.

**Fuente.** DuckDuckGo (HTML), sin clave de API ni registro. Se descartan los
enlaces de anuncios y se decodifican las URLs envueltas en el redirect.

> DuckDuckGo limita el tráfico automatizado y puede responder `202`/`429` durante
> un rato. Entonces el asistente dice que no pudo buscar, no inventa. Para uso
> intensivo conviene un proveedor con clave.

**Coste medido.** 2,2 s con búsqueda frente a 0,3–0,6 s sin ella.

**Detalles que costaron encontrar:**

- Ollama devuelve **vacío** si el historial contiene `tool_calls` y no se le vuelven
  a pasar las herramientas en la llamada final.
- La respuesta tras buscar tiende a salir con listas y enlaces. No se corrige solo
  con el prompt: hay un limpiador (`atlas/core/text_utils.py`) que quita markdown,
  emojis, tablas, URLs y puntuación huérfana, y se aplica a la vista, al historial
  y al texto que va al sintetizador.
- La herramienta captura **cualquier** excepción y devuelve texto: una búsqueda
  fallida no puede tumbar el turno.

**Lo que queda pendiente.** Más herramientas (calculadora, hora, clima) y servidores
MCP, que solo compensan cuando hay integraciones ya existentes que reutilizar.

---
### 2. Interfaz: interactividad y navegación

**Qué aporta.** Hoy todo cabe en una pantalla; con archivos, cámara y herramientas
eso deja de ser cierto.

- **Navegación lateral** (`NavigationRail`) con secciones: Conversación, Archivos,
  Cámara, Herramientas y Ajustes.
- **Ajustes en pantalla**: voz, umbral de silencio, modelo y nombre, hoy solo por
  variables de entorno.
- **Historial navegable**: buscar, exportar la conversación, reabrir un turno.
- **Estado del sistema**: dispositivo activo, nivel de micrófono, latencias por etapa
  (las latencias ya existen en el pie).

**Riesgo.** La animación del núcleo hace `page.update()` a 20 fps. Con más widgets
en pantalla hay que bajarla a 10–12 fps o animar solo cuando hay audio.

---

### 3. Cámara en tiempo real

**Qué aporta.** Enseñarle algo en lugar de describirlo: «mira este error», «¿qué
ingrediente es este?».

**Cómo hacerlo.** Capturar con OpenCV en un hilo, codificar JPEG cada N ms y
enviarlo como `images` a `/api/chat`. La visión ya está verificada; el visor puede
ser un `ft.Image` con base64.

**Matiz importante.** Esto **no es vídeo en tiempo real**. El modelo analiza
fotogramas sueltos, uno a uno, con 1–2 s por imagen. Lo honesto es hablar de
*instantáneas periódicas* o de un botón «mira esto», no de comprender movimiento.

**Requisitos.** `opencv-python`.

**Riesgos.** Coste por fotograma (cientos de tokens visuales), CPU, y un indicador
visible de cámara activa: es audio y vídeo del usuario.

---

### 4. Carga de archivos: texto, voz y vídeo

| Tipo | Cómo se procesaría | Dependencia |
|---|---|---|
| **Texto** | Leer, trocear si es largo y añadir al contexto | ninguna |
| **Voz** | Reutiliza el ASR actual: WAV/FLAC directo; MP3/M4A necesitan ffmpeg | `ffmpeg` |
| **Vídeo** | Muestrear fotogramas a N fps y enviarlos en lote para un resumen cronológico | `ffmpeg` u OpenCV |

**Lo bueno.** La voz no exige código nuevo: el mismo `transcribe()` sirve para un
archivo y para el micrófono.

**Lo delicado.** El vídeo no es nativo: hay que decidir cuántos fotogramas y cuáles
(1 por segundo, escenas clave, o los que quepan en contexto). Un vídeo de 10
minutos a 1 fps son 600 imágenes, imposible en una sola petición: hay que resumir
por tramos.

---

### Orden sugerido

| Paso | Aporte | Esfuerzo | Depende de |
|---|---|---|---|
| 1. Ajustes en pantalla | Alto: deja de exigir variables de entorno | Bajo | — |
| 2. Carga de texto y voz | Alto: aprovecha lo que ya existe | Bajo | `ffmpeg` para MP3 |
| 3. Herramientas propias (3–4) | Alto: hora, fecha, calculadora, archivos | Medio | — |
| 4. Navegación por secciones | Medio: necesario cuando crezca | Medio | 1 y 2 |
| 5. Cámara bajo demanda | Medio-alto: visión ya verificada | Medio | `opencv-python` |
| 6. Servidores MCP | Alto, pero exige selección fiable | Alto | 3 |
| 7. Vídeo por muestreo | Medio: coste alto por minuto | Alto | `ffmpeg` |

---

### Lo que no recomiendo

- **Muchas herramientas a la vez** con este modelo: falla al elegir. Si el objetivo
  es un asistente con decenas de herramientas, el cerebro debe ser más grande;
  este modelo puede quedarse para oído y voz.
- **Vídeo continuo**: no es un modelo de vídeo. Vender «tiempo real» aquí sería
  engañoso; instantáneas sí, flujo continuo no.

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