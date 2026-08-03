# Preparación offline de una canción

`prepare_song` convierte la carpeta de entrada de una canción en un manifiesto
versionado antes de abrir REAPER. Es la gatera entre los archivos suministrados
y cualquier cerebro u orquestador posterior.

## Flujo

1. Busca stems, MIDI y mezcla completa de referencia.
2. Empareja cada MIDI con su stem mediante nombres normalizados.
3. Clasifica roles y genera nombres de pista únicos.
4. Valida duración, sample rate, duplicados exactos y tempo MIDI.
5. Comprueba si los reportes de limpieza MIDI corresponden al hash actual.
6. Construye un plan de importación que permanece con `execute: false`.
7. Escribe `sessions/<canción>/song-manifest.json` sólo cuando se invoca
   `prepare_song`.

La operación no abre REAPER, no modifica `media/` y no importa pistas.

## Análisis rápido y profundo

`analysis_level=metadata` lee formato, canales, duración y hashes. Es el modo
predeterminado y sirve para validar rápidamente una entrega.

`analysis_level=signal` agrega LUFS, picos, RMS, factor de cresta, silencios,
correlación estéreo, offset DC y muestras potencialmente saturadas. Estas
mediciones son observaciones y no producen decisiones de mezcla.

## MCP

- `preview_song_preparation` devuelve el manifiesto con
  `outputs_written: false` y está declarado como sólo lectura.
- `prepare_song` escribe el manifiesto de forma atómica dentro de `sessions/`.
  Es no destructivo e idempotente.

Ejemplo conceptual:

```text
prepare_song(
  song_name="Mi Pequeño Sol",
  bpm=85,
  source_kind="suno_stems",
  analysis_level="signal"
)
```

## CLI

```powershell
.\.venv-pampapilot\Scripts\python.exe .\scripts\prepare_song.py `
  "Mi Pequeño Sol" 85 --analysis-level signal
```

Agregar `--preview` ejecuta todas las validaciones sin escribir el manifiesto.

## Política para stems de Suno

El manifiesto conserva los niveles relativos: propone faders en `0 dB`, no
normaliza cada stem y fija el audio a timebase absoluto. La referencia se
planifica como una pista inicialmente silenciada. Cualquier rebalanceo o FX
pertenece a una etapa posterior y debe tener una razón verificable.

El plan generado contiene rutas, orden, roles, nombres, BPM y compás, pero
`execute` siempre es `false`. Una operación REAPER separada tendrá que validar
el proyecto activo antes de materializarlo.
