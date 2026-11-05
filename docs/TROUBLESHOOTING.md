# Solución de problemas

Cada entrada corresponde a un fallo real observado durante el desarrollo, con la
causa comprobada y la corrección aplicada.

---

## No entiende lo que digo

**Primero mira el pie de la ventana.** El primer número es la duración del audio
capturado:

```
audio 2.4s · ASR 0.51s · 1er token 0.09s · 1er audio 0.73s · total 2.4s
```

| Observación | Diagnóstico | Acción |
|---|---|---|
| `audio` ≈ lo que hablaste y falla | La captura está bien; el límite es el modelo | Ver *Calidad de transcripción* |
| `audio` mucho menor | El detector corta antes de tiempo | `VA_VAD_SILENCE=2.2` |
| `audio` = 0.0s | No se abrió el micrófono | Otro dispositivo en el desplegable |

### Calidad de transcripción

Un modelo ómnibus de 1,73 B en Q4 no es un motor de reconocimiento. Si la captura
es correcta y aun así falla, las opciones son:

1. Hablar más cerca del micrófono (los arrays de portátil captan lejos y con eco).
2. Un ASR dedicado (`faster-whisper`) manteniendo LFM3 solo para conversar.

---

## Se interrumpe solo mientras habla

**Causa:** eco del altavoz. El micrófono oye al asistente y lo interpreta como
una interrupción del usuario.

| Solución | Efecto |
|---|---|
| Auriculares | Elimina el eco por completo |
| `VA_BARGE_MIN_LEVEL=1200` | Exige más volumen para interrumpir |
| `VA_BARGE_IN=0` | Desactiva la interrupción |

---

## La voz suena entrecortada

**Causa más frecuente:** salida Bluetooth. Añade 150–300 ms de latencia y cortes
ocasionales; en modo manos libres baja a 8–16 kHz.

Cambia la salida a altavoces o cable en el desplegable **Salida**.

**Causa histórica (ya corregida):** el WAV de Ollama declara un tamaño de datos
falso (se midieron 89.478 s para un clip de 0,5 s). Si el código durmiera esa
duración, la app quedaría congelada. La duración se calcula con los bytes reales.

---

## El asistente no responde nunca

1. Comprueba que el pie no diga «No se escuchó voz».
2. Si nunca aparece «Te escucho…», el detector no lo oye:
   - sube el volumen del micrófono en Windows,
   - baja `VA_VAD_MIN_SPEECH` a 0.3.

---

## No se pudo conectar con Ollama

```powershell
ollama list
```

Si eso falla, el servicio no está corriendo. Si funciona pero la app no conecta,
revisa `VA_BASE_URL`.

---

## El modelo no está instalado

El nombre debe coincidir exactamente. `ollama list` muestra el real.

> Aviso: el README del tutorial original menciona `lfm3-omni:2b-q8`. Ese tag
> **no existe** en este equipo; el instalado es `lfm3-omni:2b` (Q4_K_M).

---

## Error al instalar dependencias (pyyaml, Visual C++)

Ocurre con Python demasiado nuevo, sin wheels precompilados. `pyyaml` tiene
wheels hasta cp314; en cp315 intenta compilar y exige MSVC.

Solución: usar **Python 3.13**. Y para detectar el problema antes de compilar:

```powershell
python -m pip install --only-binary=:all: -r requirements.txt
```

---

## La búsqueda dice que no está disponible

**Causa:** DuckDuckGo limita el tráfico automatizado y responde `202` (bloqueo
blando) o `429`. No es un fallo del código: el endpoint gratuito no tiene clave ni
cuota acordada, y tras muchas búsquedas seguidas corta durante un rato.

**Qué hace la aplicación:** un `429` se reintenta una vez tras 1,5 s; un `202` no se
reintenta porque no mejora en segundos. En ambos casos el asistente responde que no
pudo buscar, en lugar de inventar.

**Qué puedes hacer:**

1. Esperar unos minutos (suele recuperarse solo).
2. Bajar la frecuencia de búsquedas.
3. Para uso intensivo, cambiar a un proveedor con clave (Brave, Tavily, Serper).
   La herramienta está aislada en `atlas/tools.py`: cambiar de proveedor es tocar
   una función.

---

## No saluda al abrir

- `VA_GREETING` vacío.
- O el modelo no respondió al arrancar: mira la línea de estado, que mostrará el
  error.

---

## Se equivoca en cálculos

Ejemplo real: preguntado `1250 × 4`, respondió `312.5`.

**No es un problema del prompt.** Es el tamaño del modelo. La personalidad le pide
verificar el resultado y aun así falla. Para aritmética fiable hay que resolverla
en Python antes de llamar al modelo.

---

## La interfaz va lenta

La animación hace `page.update()` a ~20 fps. En escritorio local es
despreciable; sobre red lenta conviene bajarla: en `_animate()`, cambia
`await asyncio.sleep(0.05)` por `0.08` (12 fps).

---

## Comprobar que el audio funciona sin abrir la app

```powershell
python -c "import sounddevice as sd; print(sd.query_devices())"
```

Un valor mayor o igual que cero en la columna de entrada significa que PortAudio
ve el micrófono.