# Limpieza MIDI asistida por audio

PampaPilot incluye un proceso offline reutilizable que recibe un MIDI y un WAV
del mismo instrumento. No abre el DAW ni modifica los archivos de entrada.

Produce tres artefactos:

- `clean-safe.mid`: repara solamente defectos estructurales inequívocos;
- `reconstructed.mid`: suma correcciones de altura respaldadas por el perfil y
  por el WAV, y cuantización sólo si se solicita expresamente;
- `cleanup-report.json`: registra configuración, hashes, métricas, cambios
  aplicados y propuestas no aplicadas.

## Uso

El modo neutro conserva el mapa de tempo del MIDI y no presupone instrumento:

```powershell
.\.venv-pampapilot\Scripts\python.exe .\scripts\clean_midi.py `
  "C:\ruta\instrumento.mid" `
  "C:\ruta\instrumento.wav" `
  "C:\ruta\salida"
```

Cuando el tempo y el instrumento son conocidos pueden declararse:

```powershell
.\.venv-pampapilot\Scripts\python.exe .\scripts\clean_midi.py `
  "C:\ruta\guitarra.mid" `
  "C:\ruta\guitarra.wav" `
  "C:\ruta\salida" `
  --bpm 85 --profile guitar
```

Los perfiles incluidos son `generic`, `guitar`, `bass`, `piano` y `drums`.
También se puede definir cualquier rango mediante `--min-pitch` y
`--max-pitch`. `--quantize` habilita el ajuste leve a grilla; está apagado por
defecto para no borrar interpretación ni convertir notas cercanas en
duplicados.

## Política de seguridad musical

La variante segura elimina duplicados exactos y recorta solapamientos de una o
dos unidades de tiempo entre notas de igual altura y canal. Un BPM indicado en
la línea de comandos reemplaza el mapa de tempo de forma explícita y queda
registrado en el reporte; si se omite, se conserva el mapa original.

Una corrección de octava requiere simultáneamente:

1. que la nota esté fuera del rango declarado para el instrumento;
2. que la energía CQT del WAV favorezca la alternativa por el margen configurado;
3. que la alternativa tenga suficiente energía absoluta;
4. que la corrección no colisione con otra nota activa.

Si falla el cuarto control, la posibilidad se registra como propuesta pero no
se aplica. Los onsets fuertes del WAV que no aparecen en el MIDI también se
reportan como propuestas; nunca se insertan automáticamente porque pueden ser
ataques, armónicos o artefactos de separación.

## Alcance y límites

El motor sirve para instrumentos monofónicos o polifónicos y conserva mensajes
de canal como cambios de programa, controladores y pitch bend. Está pensado
para un MIDI de interpretación y el stem correspondiente, no para comparar un
arreglo MIDI multitimbral completo con un único WAV mezclado.

La salida consolida la interpretación en una pista MIDI y no copia metadatos
como letras, marcadores o nombres de secciones; el reporte cuenta los metadatos
omitidos. Un stem separado por IA puede contener falsos armónicos y ataques, de
modo que la aceptación perceptual sigue requiriendo una escucha posterior.

## API de Python

La configuración es una estructura estable e independiente del agente o DAW:

```python
from pathlib import Path

from pampapilot.midi_cleanup import CleanupConfig, run_cleanup

report = run_cleanup(
    Path("instrumento.mid"),
    Path("instrumento.wav"),
    Path("salida"),
    config=CleanupConfig(
        bpm=None,
        profile="generic",
        minimum_pitch=36,
        maximum_pitch=84,
        enable_quantization=False,
    ),
)
```

Esto permite exponer el mismo motor más adelante por MCP, por una interfaz web
o por otro cerebro sin duplicar la lógica musical.

## Herramientas MCP

El servidor publica cuatro operaciones offline que no requieren conexión con
REAPER:

- `discover_song_media`: encuentra stems, MIDI, referencia y propone pares por
  nombre normalizado;
- `analyze_midi`: inspecciona estructura, tempo y reparaciones seguras sin leer
  audio;
- `preview_midi_cleanup`: ejecuta todo el análisis MIDI/WAV, pero devuelve un
  `dry-run` con `outputs_written: false`;
- `clean_midi_files`: genera las dos variantes y el reporte bajo `sessions/`.

Por seguridad, las tres operaciones de análisis sólo aceptan entradas ubicadas
en `media/` o `sessions/`. La operación de generación únicamente puede escribir
dentro de `sessions/`, incluso si un cerebro solicita otra ruta. El MCP marca
descubrimiento, análisis y previsualización como sólo lectura; la generación se
marca como escritura no destructiva e idempotente.

El análisis CQT puede tardar varios segundos en temas completos. Por eso la
configuración de ejemplo del cliente asigna 120 segundos a las llamadas MCP.
