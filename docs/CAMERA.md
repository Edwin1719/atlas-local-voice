# Propuesta: cámara bajo demanda en Atlas

**Estado:** implementado en 0.13 (2026-11-06).
**Objetivo:** añadir una cámara a la interfaz para aprovechar la visión de
`lfm3-omni:2b` sin convertir el asistente en un modelo de vídeo ni romper el
pipeline de voz.

## 0. Implementación

- `atlas/vision/camera.py`: captura en un hilo, preview JPEG y snapshot;
  `cv2` se importa de forma perezosa.
- Tarjeta CÁMARA en el lateral e icono en la cabecera; «Mira esto» adjunta una
  instantánea y se consume en la siguiente pregunta.
- `supports_vision()` consulta `/api/show` antes de abrir el dispositivo.
- La imagen va como `images` (base64) solo en la llamada final; la decisión
  sigue siendo texto.
- Prueba física con la **HP Wide Vision HD Camera**: preview 640×360 JPEG de
  ~18,5 KB, snapshot 1280×720 de ~129 KB, sin guardar fotogramas.
- 87 pruebas OK (11 nuevas: cámara, imagen y UI).

---

## 1. Lo que ya está verificado

### 1.1 El modelo sí ve imágenes

`/api/show` de Ollama confirma las capacidades de `lfm3-omni:2b`:

```
completion, vision, audio, speech, tools
```

La API de Ollama acepta imágenes en el mensaje del usuario:

```json
{"role": "user", "content": "¿Qué ves?", "images": ["<base64>"]}
```

Documentación: <https://docs.ollama.com/capabilities/vision>

### 1.2 Flet 1.1.0 puede mostrar los fotogramas

`ft.Image.src` acepta **URL, ruta local, base64 o bytes crudos** (verificado en
el código de Flet 1.1.0). No hace falta convertir cada fotograma a base64 a mano:
se puede asignar el JPEG como `bytes`. Si el cliente no pintara bytes crudos, el
fallback es un data URI `data:image/jpeg;base64,...`.

### 1.3 OpenCV funciona en este equipo

- `opencv-python-headless==5.0.0.93` tiene rueda `cp37-abi3-win_amd64` para
  Python 3.13; se probó lectura de un vídeo sintético y, ya en la implementación,
  la cámara física: preview 640×360 JPEG y snapshot 1280×720.
- Un fotograma sintético de 640×480 a calidad 60 pesa ~8,5 KB; uno real pesará
  más, pero sigue siendo manejable en local.
- La cámara del equipo está presente y habilitada a nivel de sistema:
  **HP Wide Vision HD Camera**. No se abrió durante el análisis para no capturar
  el entorno del usuario; la prueba de hardware queda para el paso de
  implementación.

### 1.4 Lo que el modelo hace bien y lo que no

Prueba con imágenes sintéticas, `lfm3-omni:2b`:

| Imagen | Pregunta | Resultado | Tiempo |
|---|---|---|---|
| Fondo rojo, círculo azul, texto «ATLAS 42» | describir color/figura/texto | Correcto en color y figura; leyó «ATLAS42» | 4,07 s (frío) |
| Diálogo «ERROR 404 / Archivo no encontrado / C:\datos\informe.pdf» | citar código y archivo | Leyó «ERROR 40.4» y «C:\dates\informe.pdf» | 0,43–0,95 s (caliente) |

**Conclusión honesta:** el modelo describe objetos, colores y escenas, pero el
**OCR no es fiable** a 1,73 B. Para «mira este error» hay que fijar expectativas o
añadir OCR/modelo mayor en una fase posterior. No se debe vender como lector de
texto.

Comparativa con otros modelos instalados (misma imagen de error, `think=False`):

| Modelo | Respuesta | Tiempo |
|---|---|---|
| `lfm3-omni:2b` | ERROR 40.4; ruta incorrecta | ~0,9 s |
| `qwen3.5:4b` | ERROR 404; `informe.pdf` | ~10,6 s |
| `gemma4:e2b` | ERROR 404; `C:\datos\informe.pdf` | ~7,8 s |

Los modelos mayores leen mejor, pero no ofrecen el conjunto audio + voz + visión
de `lfm3-omni` y multiplican la latencia. Para v1, mantener `lfm3-omni`; el OCR
fiable es una fase 2.

### 1.5 Por qué OpenCV si el modelo ya ve

El modelo **entiende** imágenes, pero no las **captura**. Ollama es un servidor
local: recibe los bytes que le envía la aplicación; no tiene acceso a la cámara
del equipo. Flet 1.1.0 tampoco trae un control de cámara (`ft.Camera` no existe).

```
[cámara HP] --OpenCV--> [JPEG] --base64--> [Ollama /api/chat images] --> [modelo]
```

OpenCV aporta la pieza que falta: abrir el dispositivo, leer fotogramas,
redimensionar, codificar JPEG y liberar la cámara. El modelo aporta la
comprensión; la interfaz, la vista previa; OpenCV, la captura.

Alternativas consideradas:

| Opción | Veredicto |
|---|---|
| `opencv-python-headless` | Una rueda, `VideoCapture` + `imencode`, Windows/Linux/macOS, probado |
| `ffmpeg` + dshow | Funciona, pero exige binario externo y gestionar procesos |
| `pygrabber` / Media Foundation | Más complejo y específico de Windows |
| `flet-camera` (tercero) | No instalado; soporte de escritorio incierto |
| `getUserMedia` del navegador | Solo si la app fuera web; aquí es escritorio |
| `ft.FilePicker` | Analiza una imagen existente, pero no es cámara en vivo |

**Por qué `headless`:** solo se usan `VideoCapture` e `imencode`; no hace falta
la GUI de OpenCV. La rueda es más pequeña y evita dependencias de ventanas.
**Por qué 5.0.0.93:** es la versión probada con Python 3.13 en este equipo;
`opencv-python` completo o una 4.x también servirían, pero se pinea lo probado.

**Para no imponerla:** `camera.py` importa `cv2` de forma perezosa. Si no está
instalado, el botón de cámara muestra «Instala opencv-python-headless» y el resto
del asistente sigue funcionando. Así el núcleo de voz no depende de la cámara.

---

## 2. Decisión de producto: instantáneas, no vídeo

El modelo analiza **fotogramas sueltos**, no movimiento. La propuesta es:

- **Vista previa en vivo** en la interfaz (para encuadrar).
- **Botón «Mira esto»**: captura una instantánea y la adjunta a la **próxima**
  pregunta.
- **Sin envío automático de todos los fotogramas**: solo se manda la instantánea
  adjunta, una vez.
- **Cámara apagada por defecto**, con indicador visible cuando está activa.

Esto evita tres problemas: coste por fotograma, latencia y exposición innecesaria
de la cámara.

### 2.1 Flujo de uso

```
1. El usuario pulsa el icono de cámara.
2. Aparece la tarjeta CÁMARA con la vista previa.
3. Encuadra y pulsa «Mira esto».
   → se guarda un JPEG en memoria y se muestra «Se enviará con tu próxima pregunta».
4. El usuario pregunta por voz: «¿Qué ingrediente es este?».
5. El turno se transcribe y la pregunta se envía al modelo con la imagen.
6. El asistente responde por voz; la imagen se descarta.
```

La imagen se consume **una vez**. Para una segunda pregunta sobre lo mismo, se
vuelve a pulsar «Mira esto». Así no se reenvía sin querer y no se guarda nada.

---

## 3. Arquitectura quirúrgica

### 3.1 Módulo nuevo

```
atlas/vision/__init__.py
atlas/vision/camera.py     # CameraWorker: hilo de captura, preview y snapshot
```

No se toca el pipeline de audio. La cámara es un productor de imágenes; el turno
de voz sigue igual y solo recibe un `image_jpeg` opcional.

### 3.2 `CameraWorker`

- Hilo daemon con `threading.Event` para parar y `threading.Lock` para el último
  fotograma.
- Abre `cv2.VideoCapture(index, cv2.CAP_DSHOW)` en Windows; si falla, prueba el
  backend por defecto.
- Configura 1280×720 y 30 fps; si la cámara no lo acepta, usa lo que entregue.
- Guarda el último fotograma BGR y codifica una vista previa de 640 px de ancho
  (640×360 en 16:9) JPEG q60 a ~8 fps. El snapshot se codifica a 1280×720 q85
  solo cuando se pide.
- Expone `active`, `error`, `preview() -> (seq, jpeg)`, `snapshot() -> bytes | None`,
  `start()`, `stop()`.
- Si `cap.read()` falla, registra el error y reintenta; no tumba la app.
- `stop()` libera la cámara y hace `join` con timeout.

### 3.3 Integración con el turno

```python
# _finish_turn, después de transcribir y validar el texto
image, self._pending_image = self._pending_image, None
self._add_bubble("user", text, with_image=bool(image))
await self._respond(text, asr_seconds, image=image)
```

`_messages_for` añade la imagen solo al mensaje del usuario actual:

```python
user = {"role": "user", "content": user_text}
if image:
    user["images"] = [base64.b64encode(image).decode("ascii")]
```

La **llamada de decisión** sigue siendo solo texto: no se duplica el coste de
visión para decidir si se busca. La **llamada final** recibe la imagen. Si hay
herramienta, `mensajes` conserva la imagen en el mensaje del usuario.

### 3.4 Comprobación de capacidad

Añadir a `VoiceClient`:

```python
async def supports_vision(self) -> bool:
    response = await self._http.post("/api/show", json={"model": self._settings.model})
    return "vision" in response.json().get("capabilities", [])
```

Al encender la cámara, si el modelo no declara `vision`, se muestra un error claro
y no se abre el dispositivo.

### 3.5 Cambios de configuración

En `Settings`:

| Variable | Defecto | Uso |
|---|---|---|
| `VA_CAMERA_INDEX` | `0` | Índice de cámara |
| `VA_CAMERA_WIDTH` | `1280` | Ancho de captura |
| `VA_CAMERA_HEIGHT` | `720` | Alto de captura |
| `VA_CAMERA_PREVIEW_FPS` | `8` | FPS de la vista previa |

No hay `VA_CAMERA_ENABLED`: la cámara se enciende desde la interfaz y nunca al
arrancar.

---

## 4. Interfaz

### 4.1 Ubicación

La pantalla actual es `Row(principal, lateral)`; el lateral mide 310 px y ya
contiene ACTIVIDAD. La opción menos invasiva es una **tarjeta CÁMARA en la parte
superior del lateral**, oculta por defecto:

```
┌──────────────────────────────┐
│ CÁMARA            ● activa   │
│ ┌──────────────────────────┐ │
│ │       vista previa       │ │
│ └──────────────────────────┘ │
│ [Mira esto]     [Apagar]     │
│ «Se enviará con tu próxima   │
│  pregunta»                   │
├──────────────────────────────┤
│ ACTIVIDAD                    │
└──────────────────────────────┘
```

El icono de cámara va en la cabecera, junto al estado, para abrir/cerrar la
tarjeta sin añadir otro bloque al pie.

### 4.2 Controles

- **Icono de cámara** en la cabecera: abre/cierra; punto rojo cuando está activa.
  Cerrar la tarjeta apaga la cámara: no queda capturando en segundo plano.
- **Encender/Apagar** dentro de la tarjeta.
- **Mira esto**: captura la instantánea; deshabilitado hasta el primer fotograma.
- **Miniatura adjunta**: la propia vista previa; un texto confirma que se enviará.
- **Descartar**: un icono «x» para quitar la instantánea pendiente.
- **Estado**: «Cámara activa», «No se pudo abrir», «La cámara está en uso».

### 4.3 Actualización de la vista previa

`_animate()` ya llama a `page.update()` cada 50 ms. La cámara se actualiza ahí,
no en un bucle nuevo:

```python
def _paint_camera(self) -> None:
    if not self.camera.active or not self.camera_card.visible:
        return
    seq, jpeg = self.camera.preview()
    if jpeg and seq != self._camera_seq:
        self._camera_seq = seq
        self.camera_image.src = jpeg
```

Así se evita un segundo `page.update()` y se limita la vista previa a ~8 fps.
Cuando la cámara está apagada, no se toca nada.

### 4.4 Burbuja con imagen

`_add_bubble("user", texto, with_image=True)` añade una etiqueta pequeña
«imagen adjunta» debajo de la transcripción. El historial del modelo sigue siendo
solo texto; la etiqueta es de interfaz.

---

## 5. Prompt y comportamiento

Añadir al prompt de sistema:

> «Si recibes una imagen, describe solo lo que se ve. Si no puedes leer un texto
> o no estás seguro, dilo; no inventes detalles.»

La instrucción posterior a una herramienta sigue siendo específica de noticias
(«qué pasó, dónde y cuándo»). Conviene generalizarla en esta misma iteración:

> «Responde en voz alta con el resultado de la herramienta, en una o dos frases,
> sin listas ni markdown. Si la herramienta falló, dilo.»

Sin esto, un turno de cámara que además busque en internet recibiría una
instrucción de noticias que no encaja.

---

## 6. Rendimiento medido y esperado

| Etapa | Medición |
|---|---|
| Prefill de visión (640×480) | ~334–338 tokens |
| Respuesta de visión en caliente | 0,43–0,95 s |
| Primera respuesta (modelo frío) | ~4 s |
| Vista previa de 640 px de ancho q60 | ~18 KB reales (640×360) |
| Captura 1280×720 + JPEG | milisegundos en el hilo; no bloquea asyncio |

La vista previa a 8 fps no debería competir con el audio: la captura y el JPEG
van en un hilo; el bucle asyncio solo asigna bytes a `ft.Image`. El modelo sigue
siendo el coste dominante.

---

## 7. Privacidad y seguridad

- **Apagada por defecto**; solo se enciende con una acción explícita.
- **Indicador visible**: punto rojo y texto «Cámara activa».
- **Sin disco**: los fotogramas viven en memoria; no se guardan ni se registran.
- **Solo Ollama local**: la imagen no se envía a la búsqueda web ni a terceros.
- **Se consume una vez**: después del turno se borra; «Limpiar» también la borra.
- **Se libera** al apagar la cámara y en `shutdown()`.
- **Sin frases del usuario en logs** ni base64 en mensajes de error.
- La cámara puede estar bloqueada por Windows/antivirus; el error se muestra sin
  intentar rodearlo.

---

## 8. Pruebas

**Unitarias, sin hardware**

- `CameraWorker` con un `VideoCapture` falso: arranque, preview con secuencia,
  snapshot, parada y error de lectura.
- Codificación JPEG: un `numpy.ndarray` BGR produce bytes `\xff\xd8` y dimensiones
  correctas.
- `_messages_for(..., image=...)`: el mensaje del usuario lleva `images` con el
  base64 exacto; sin imagen, no lleva la clave.
- `_respond` con `image`: un `stream_events` falso captura los mensajes y
  comprueba que la imagen solo está en la llamada final, no en la de decisión.
- `supports_vision()`: respuesta falsa de `/api/show` con y sin `vision`.
- La imagen se consume: tras `_respond`, `_pending_image` es `None`.

**Integración manual**

- Encender la HP Wide Vision HD Camera; vista previa ≥ 8 fps.
- «Mira esto» + «¿qué ves?» → describe la escena.
- Texto grande («ERROR 404») → comprobar que el OCR puede fallar y que el
  asistente no inventa.
- Apagar la cámara → el dispositivo se libera; se puede abrir en otra app.
- Cámara en uso por otra aplicación → mensaje claro.
- Modelo sin `vision` → error claro, sin abrir la cámara.
- Sin imagen adjunta → el turno sigue siendo solo voz.

---

## 9. Plan de implementación

| Paso | Cambio | Esfuerzo |
|---|---|---|
| 1 | `opencv-python-headless==5.0.0.93`; `atlas/vision/camera.py`; tests con captura falsa | 2–3 h |
| 2 | `supports_vision()` y `images` en `_respond`/`_messages_for`; tests | 2 h |
| 3 | Tarjeta CÁMARA, icono, preview en `_animate`, snapshot y miniatura | 3–4 h |
| 4 | Integración con `_finish_turn`, consumo único, burbuja con imagen, prompt | 1–2 h |
| 5 | Documentación, pruebas manuales con la cámara y ajustes | 2 h |

Total: **~1–1,5 días**. La lectura/codificación y la visión ya están validadas
por separado; la captura de la cámara física se valida en el paso 1. Lo que falta
es integrar todo con la interfaz y el turno.

**Criterios de aceptación**

- La cámara está apagada al arrancar; no se abre ningún dispositivo.
- Encender muestra vista previa estable y apagar la libera.
- «Mira esto» adjunta una instantánea; la siguiente pregunta la envía y la
  respuesta la usa.
- Sin instantánea, el turno es solo voz.
- La imagen no se guarda en disco ni se envía a la búsqueda web.
- Un modelo sin visión o una cámara ocupada muestran error y la app sigue.
- 87 tests OK, con pruebas nuevas del camino de imagen.

---

## 10. Riesgos y límites

| Riesgo | Mitigación |
|---|---|
| OCR poco fiable en 1,73 B | No prometer lectura de texto; fase 2 con OCR/modelo mayor |
| Alucinación sobre la imagen | Prompt «describe solo lo que se ve; si no, dilo» |
| Privacidad | Apagada por defecto, indicador, sin disco, solo Ollama local |
| Peso de la vista previa en Flet | 640 px q60 a 8 fps; solo se actualiza si hay frame nuevo |
| Driver/cámara ocupada en Windows | `CAP_DSHOW`, fallback, error claro |
| CPU con captura + modelo | Hilo separado, preview limitada, snapshot bajo demanda |
| Contexto por tokens de imagen | ~338 tokens; una imagen por turno, sin historial |
| Segunda pregunta sobre la misma imagen | Se vuelve a capturar; opción «mantener» en fase 2 |

---

## 11. Decisiones tomadas

1. **Interacción:** «Mira esto» + adjuntar a la siguiente pregunta.
2. **Ubicación:** tarjeta en el lateral + icono en la cabecera.
3. **Resolución:** snapshot 1280×720 / preview de 640 px a 8 fps.
4. **Modelo:** `lfm3-omni:2b` (rápido; OCR flojo, documentado).
5. **Imagen pegajosa:** no; se consume una vez.
6. **Implementación:** pasos 1–5 ejecutados.

**Pendiente para fase 2:** OCR o segundo modelo para texto, opción «mantener
imagen», nombres de dispositivos y adjuntar la imagen también a la llamada de
decisión.

---

## Apéndice: bocetos

### `CameraWorker`

```python
import sys
import threading
import time

import cv2


class CameraWorker:
    def __init__(self, index=0, width=1280, height=720,
                 preview_width=640, preview_quality=60, preview_fps=8.0):
        self.index = index
        self.width = width
        self.height = height
        self.preview_width = preview_width
        self.preview_quality = preview_quality
        self.preview_interval = 1.0 / max(1.0, preview_fps)
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._frame = None
        self._preview = None
        self._seq = 0
        self._error = ""
        self._thread = None

    @property
    def active(self):
        return self._thread is not None and self._thread.is_alive()

    @property
    def error(self):
        return self._error

    def start(self):
        if self.active:
            return
        self._stop.clear()
        self._error = ""
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _open(self):
        backends = [cv2.CAP_DSHOW, cv2.CAP_ANY] if sys.platform == "win32" else [cv2.CAP_ANY]
        for backend in backends:
            cap = cv2.VideoCapture(self.index, backend)
            if cap.isOpened():
                return cap
            cap.release()
        return None

    def _run(self):
        cap = self._open()
        if cap is None:
            self._error = "No se pudo abrir la cámara."
            return
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        cap.set(cv2.CAP_PROP_FPS, 30)
        last_preview = 0.0
        try:
            while not self._stop.is_set():
                ok, frame = cap.read()
                if not ok:
                    self._error = "La cámara no entrega imagen."
                    time.sleep(0.1)
                    continue
                with self._lock:
                    self._frame = frame
                    self._error = ""
                now = time.monotonic()
                if now - last_preview >= self.preview_interval:
                    small = cv2.resize(frame, (self.preview_width, int(
                        self.preview_width * frame.shape[0] / frame.shape[1]
                    )))
                    ok, buf = cv2.imencode(
                        ".jpg", small,
                        [int(cv2.IMWRITE_JPEG_QUALITY), self.preview_quality],
                    )
                    if ok:
                        with self._lock:
                            self._preview = buf.tobytes()
                            self._seq += 1
                        last_preview = now
        finally:
            cap.release()

    def preview(self):
        with self._lock:
            return self._seq, self._preview

    def snapshot(self, quality=85):
        with self._lock:
            frame = None if self._frame is None else self._frame.copy()
        if frame is None:
            return None
        ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
        return buf.tobytes() if ok else None

    def stop(self):
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=2.0)
```

### Mensaje con imagen

```python
import base64

user = {"role": "user", "content": user_text}
if image_jpeg:
    user["images"] = [base64.b64encode(image_jpeg).decode("ascii")]
```
