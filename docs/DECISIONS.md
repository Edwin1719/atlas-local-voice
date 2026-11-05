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