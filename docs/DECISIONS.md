# Decisiones de diseño

Registro breve de las decisiones que cambiaron el proyecto, con el problema que
las motivó. Todas se tomaron tras medir el fallo, no por preferencia.

---

## ADR-001 · Audio con PortAudio en lugar de los widgets de Flet

**Contexto.** `flet-audio` y `flet-audio-recorder` daban dos fallos
estructurales: la tasa de muestreo era una incógnita (podía entregar 44,1 o 48 kHz
mientras el código asumía 16 kHz) y la reproducción era un widget por clip.

**Consecuencia medida.** Con 48 kHz declarados como 16 kHz, el modelo oía el audio
a un tercio de velocidad y el detector de silencio cortaba a los 0,53 s reales en
lugar de 1,6 s.

**Decisión.** Captura y reproducción por PortAudio (`sounddevice`). Flet queda
como interfaz.

**Coste.** Una dependencia más y la obligación de elegir dispositivo a mano.
**Beneficio.** Tasa garantizada, reproducción sin cortes y control de interrupción.

---

## ADR-002 · Detector con suelo de ruido adaptativo

**Contexto.** Un umbral fijo funciona en una habitación y falla en otra.

**Decisión.** Estimar el nivel de fondo con una media exponencial que solo se
actualiza cuando no hay voz, y disparar con `max(fondo × 3, 200)`.

**Por qué solo en silencio.** Si se actualizara durante el turno, la propia voz
subiría el suelo y el detector se cerraría a sí mismo.

**Validación.** Con ruido de fondo de 300: cero turnos falsos, y detección correcta
de voz a 2500.

---

## ADR-003 · TTS por frase con cola continua

**Contexto.** Sintetizar la respuesta completa antes de reproducir añade segundos
de espera. Reproducir clip a clip cortaba las frases.

**Decisión.** Sintetizar por frase y encolar el PCM en un reproductor continuo
cuyo callback consume la cola muestra a muestra.

**Por qué no `sleep(duración)`.** Fue el primer enfoque y falló: el WAV de
Ollama declara un tamaño de datos falso, así que la duración calculada llegó a
89.478 s y la app quedó congelada.

---

## ADR-004 · Un único bucle de audio

**Contexto.** Hacen falta dos comportamientos simultáneos: escuchar para el turno y
escuchar para detectar interrupciones.

**Decisión.** Un solo bucle cada 50 ms que enruta según el estado, en lugar de dos
bucles compitiendo por el mismo buffer.

**Alternativa descartada.** Callbacks de `asyncio` desde el hilo de PortAudio:
introduce contención y errores al cerrar el dispositivo. El hilo solo escribe en un
buffer con `threading.Lock`.

---

## ADR-005 · El nombre como única fuente de verdad

**Contexto.** El nombre aparecía en el saludo, en la identidad del modelo y en la
documentación; cambiarlo exigía tocar tres sitios.

**Decisión.** `VA_NAME` alimenta `greeting_text` y `system_text` mediante
un reemplazo de `{name}`, no de `str.format`.

**Por qué no `format`.** Un prompt propio con llaves se rompería.

---

## ADR-006 · Endpoints compatibles con OpenAI para el audio

**Contexto.** `/api/chat` acepta el campo `audio` pero lo **ignora en
silencio**: devuelve el prompt como eco.

**Decisión.** Audio de entrada por `/v1/chat/completions` con `input_audio`,
y síntesis por `/v1/audio/speech`. Solo el LLM usa `/api/chat` (NDJSON).

**Detalle.** `/v1/audio/speech` cierra el chunked sin terminador; la lectura debe
ser tolerante o httpx lanza `RemoteProtocolError`.

---

## ADR-007 · Personalidad en el prompt, no en el código

**Contexto.** Las respuestas salían con listas y markdown, ilegibles al convertselas
en voz.

**Decisión.** Reglas explícitas en el prompt de sistema: frases cortas, sin listas,
sin emojis, números escritos como se pronuncian, y no repetir la pregunta.

**Límite conocido.** Las reglas mejoran el estilo, pero no arreglan la aritmética:
un modelo de 1,73 B en Q4 sigue calculando mal.

---

## ADR-008 · Google News RSS para noticias, DuckDuckGo para el resto

**Contexto.** `buscar_web` usaba DuckDuckGo para todo. Con «últimas noticias de
Colombia» devolvía las portadas de los medios, no las noticias: el asistente
respondía «consulta EL TIEMPO, El Espectador…» en vez de contar lo que pasó.

**Decisión.** Dentro de la misma herramienta, enrutar según la consulta: si pide
noticias, Google News RSS (titulares, medio y hora); si no, DuckDuckGo. La portada
del día se usa cuando no hay tema concreto; la búsqueda con `when:1d` cuando lo
hay. Se devuelven tres titulares como máximo y sin URLs.

**Por qué no una segunda herramienta.** El modelo de 1,73 B ya elige mal entre
opciones; una sola herramienta que enruta por dentro evita esa decisión.

**Coste.** Depender de un RSS de Google y mantener un mapa de ediciones por país.
**Beneficio.** Noticias reales en vez de recomendaciones de portales.

---

## ADR-009 · Tool calling alineado con la documentación de Ollama

**Contexto.** El flujo ya usaba `/api/chat` con `tools` y el esquema correcto,
pero se quedaba con el último fragmento de `tool_calls`, reconstruía el mensaje
del asistente con `content` vacío e ignoraba los `tool_calls` de la llamada
final. Funcionaba con lfm3-omni, que manda un único fragmento, pero no seguía el
patrón documentado.

**Decisión.** Acumular `tool_calls`, `content` y `thinking`; reconstruir el
mensaje del asistente con lo emitido; permitir una ronda extra de herramientas;
subir `num_predict` a 256 para modelos con thinking.

**Por qué.** Es el patrón de «Tool calling with streaming» y del agent loop de
Ollama. Con 96 tokens, qwen3.5 se cortaba pensando antes de llamar.

**Límite.** Dos rondas como máximo: una búsqueda no debe encadenar otra sin fin
ni disparar la latencia de voz.

---

## ADR-010 · Cámara como instantáneas bajo demanda

**Contexto.** El modelo ve imágenes, pero no captura; Flet 1.1.0 no trae cámara.
Se necesita una fuente local de JPEG y una forma de adjuntarla al turno sin
convertir el asistente en un modelo de vídeo.

**Decisión.** OpenCV headless en un hilo (captura + preview de 640 px a 8 fps +
snapshot 1280×720), tarjeta CÁMARA en el lateral, botón «Mira esto», una imagen
por turno adjunta solo a la llamada final, cámara apagada por defecto y OpenCV
importado de forma perezosa.

**Por qué no vídeo continuo.** El modelo analiza fotogramas sueltos; enviar todos
multiplica coste, latencia y exposición. La vista previa es para encuadrar, no
para el modelo.

**Por qué no adjuntar a la llamada de decisión.** Duplicaría el prefill de visión
en cada turno; para v1 la decisión de buscar sigue siendo texto.

**Límite.** El OCR de 1,73 B no es fiable; el texto grande puede leerse mal. La
fase 2 puede añadir OCR o un segundo modelo.