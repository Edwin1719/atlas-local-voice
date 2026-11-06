# Historial de versiones

## 0.13.1 — Interfaz estable + reactor

- Restaura la interfaz anterior de dos columnas y el pie original; se retira el
  HUD de tres columnas que recortaba el panel derecho y la cinta inferior.
- Integra el reactor de `atlas/ui/reactor.py` en el escenario central y ajusta
  la paleta al estilo de sala de control.
- Restaura la barra de frecuencia de 28 barras bajo el reactor, animada con el
  nivel de voz; se descarta el túnel de fondo por no alcanzar la referencia.
- Conserva la cámara: tarjeta en el lateral, vista previa, «Mira esto» y envío
  de la instantánea con la siguiente pregunta.
- 87 pruebas en verde.

## 0.13 — Cámara bajo demanda

- Cámara opcional con `opencv-python-headless`: `atlas/vision/camera.py`
  captura en un hilo, entrega vista previa JPEG y snapshot bajo demanda.
- Tarjeta CÁMARA en el lateral, icono en la cabecera y botón «Mira esto».
  Una instantánea se adjunta solo a la siguiente pregunta y se descarta después.
- La imagen viaja como `images` (base64) en la llamada final; la llamada de
  decisión sigue siendo solo texto.
- `supports_vision()` consulta `/api/show` antes de abrir la cámara.
- OpenCV se importa de forma perezosa: sin él, el resto del asistente funciona y
  la cámara muestra un aviso de instalación.
- `VA_CAMERA_INDEX`, `VA_CAMERA_WIDTH`, `VA_CAMERA_HEIGHT` y
  `VA_CAMERA_PREVIEW_FPS`.
- Once pruebas nuevas (cámara, imagen y UI); 87 en total.
- Limitación medida: el OCR de `lfm3-omni` no es fiable; se documenta.

## 0.12 — Llamado a herramientas según Ollama

- Acumula `tool_calls`, `content` y `thinking` de todos los fragmentos del
  stream; antes se quedaba con el último y podía perder fragmentos.
- El mensaje del asistente se reconstruye con `content` y `thinking`, no con un
  `content` vacío, como documenta Ollama para streaming con herramientas.
- Agent loop acotado: si el modelo pide otra búsqueda tras ver los resultados, se
  ejecuta una ronda más. Antes esa petición se ignoraba y la respuesta podía
  quedar vacía.
- `num_predict` de la llamada de decisión sube de 96 a 256: con 96, qwen3.5 se
  cortaba pensando antes de llamar a la herramienta.
- Tres pruebas nuevas (acumulación, segunda ronda y conservación de
  `content`/`thinking`); 76 en total.

## 0.11 — Noticias reales

- `buscar_web` enruta las consultas de noticias a **Google News RSS**: titulares
  reales con el medio y la hora, en lugar de las portadas que devolvía
  DuckDuckGo. El asistente ya no responde «consulta EL TIEMPO»: cuenta las
  noticias del día.
- Edición por país (Colombia por defecto): una petición genérica usa la portada
  del día y una con tema concreto usa la búsqueda con `when:1d`.
- Tres titulares como máximo y sin URLs; la instrucción de redacción exige
  hechos concretos y prohíbe recomendar portales.
- Se quitan los sufijos duplicados del medio en los títulos
  («… | El Colombiano - El Colombiano»).
- Diez pruebas nuevas: enrutado, RSS, ediciones, recencia, país y tope de
  titulares.

## 0.10 — Estabilidad

- Manejo del límite de DuckDuckGo: `429` reintenta una vez; `202` avisa sin
  reintentar. El asistente dice que no pudo buscar en vez de inventar.
- Pruebas herméticas: simulan `stream_events`, así que ya no dependen de que
  Ollama esté en marcha (7 s frente a 13 s).
- Nueva prueba del camino con herramienta y dos del manejo de límites.

## 0.9 — Búsqueda web

- Herramienta `buscar_web` con DuckDuckGo, sin clave de API.
- Bucle de herramienta en dos llamadas: decidir (sin personalidad) y redactar.
- Limpiador de markdown antes de sintetizar: la voz nunca lee listas ni enlaces.
- `VA_WEB_SEARCH` para desactivar la salida a internet.
- 16 pruebas nuevas (parser, limpieza de texto, fallos de red).
- Aviso hablado «Buscando información» antes de cada búsqueda, lanzado en paralelo
  con la consulta para no sumar latencia.
- Limpiador ampliado: emojis, tablas, parentescos vacíos, puntuación huérfana y
  signos repetidos. Se aplica también al texto mostrado y al historial, no solo al
  audio.

## 0.8 — Hoja de ruta

- Documentadas las mejoras propuestas (herramientas, MCP, interfaz, cámara,
  archivos) con su viabilidad verificada contra el modelo y el servidor.
- Verificado: *tool calling* funcional y visión por imágenes funcional.
- Aclarado que el modelo no admite vídeo nativo ni control de velocidad de voz.

## 0.7 — Voz

- Voz masculina por defecto (`male-spanish`).
- Documentado que el servidor de síntesis no admite control de velocidad.

## 0.6 — Proyecto autónomo

- Todo el proyecto vive dentro de `asistente_voz/`: ya no depende de la raíz del
  repositorio del que nació.
- El código pasa a un paquete llamado `atlas/`, con `core/`, `audio/` y `llm/`.
- `run.py` funciona desde cualquier directorio.
- `tests/` y `docs/` dentro del proyecto.
- Instalación reescrita: crear el entorno (venv o conda, nombre libre), instalar y
  ejecutar. Ya no se asume un entorno concreto.
- Documentado por qué `app.py` no se ejecuta suelto y sus dos formas de arranque.

## 0.5 — Organización y pruebas

- Código reorganizado en paquete: `core/`, `audio/` y `llm/`.
- Punto de entrada único: `run.py`.
- 35 pruebas de funcionalidad con `unittest`, sin hardware ni red.
- Las pruebas destaparon un caso límite real: si el primer bloque de audio ya
  contenía voz, el suelo de ruido se inicializaba a ese nivel y el turno nunca
  abría. El suelo inicial ahora se acota a 200.
- Documentación actualizada a la nueva estructura.

## 0.4 — Interfaz y documentación

- Interfaz rediseñada: núcleo reactivo, 28 barras, panel de actividad.
- La animación sigue el nivel real de audio (micrófono o reproducción).
- Limpieza: eliminados los archivos del tutorial y el código muerto de la etapa
  de Flet (campos de configuración sin uso, manejo de temporales).
- Documentación completa en `docs/`.

## 0.3 — Diálogo continuo

- Modo manos libres: el micrófono no se cierra entre turnos.
- Detección de turno con suelo de ruido adaptativo y pre-roll de 350 ms.
- Interrupción real con corte de la cola de reproducción.
- Saludo inicial hablado y personalidad («Atlas»).

## 0.2 — Audio real

- Migración de `flet-audio` a PortAudio: tasa garantizada y reproducción continua.
- Selección de dispositivo en la interfaz.
- Corrección del cálculo de duración del WAV (cabecera con tamaño falso).
- Corrección de la alineación PCM16 (bloques de longitud impar).

## 0.1 — Primer prototipo

- Flet + Ollama con ASR y TTS del modelo LFM3-Omni-2B.
- Diálogo por turnos con botón.
- Descubrimiento de la API real: `/v1/chat/completions` para audio de entrada y
  `/v1/audio/speech` para la síntesis.