# Materialización MIDI en REAPER

PampaPilot importa MIDI sin usar el diálogo interactivo de REAPER. Python lee y
valida el archivo; el puente Lua crea una pista y un ítem musical e inserta cada
evento en posiciones de negras del proyecto.

## Operaciones

- `import_midi`: crea una pista y un ítem MIDI.
- `import_midi_batch`: crea hasta ocho pistas dentro de una única transacción
  reversible.

Ambas operaciones exigen `project_ref`, comprueban que el BPM del proyecto
coincida y dejan las pistas silenciadas por defecto. No importan el mapa de
tempo ni modifican el tempo del proyecto.

## Verificación

Después de insertar y ordenar los eventos, el puente vuelve a leer todas las
notas mediante la API MIDI de REAPER. Para cada nota compara:

- inicio y final en ticks originales;
- canal, altura y velocidad;
- cantidad total y extensión del ítem.

También conserva y verifica los cambios de programa. Si una sola lectura no
coincide, la transacción completa se revierte. La respuesta incluye GUID de
pista, ítem y toma, resumen MIDI, hash y ruta del archivo fuente.

## Límites deliberados

La primera versión acepta hasta 8000 notas por archivo y ocho archivos por
lote. Rechaza antes de tocar REAPER cualquier MIDI con controladores, sustain,
pitch bend, aftertouch, SysEx o metadatos no soportados. Esta política evita que
una importación parezca correcta mientras pierde información interpretativa.

Los MIDI de validación de `Mi Pequeño Sol` contienen 1157 notas y un cambio de
programa cada uno. El lote de tres ocupa aproximadamente 266 KB frente al
límite de protocolo de 1 MB.

## Comparación A/B propuesta

Sobre una copia del proyecto se crean, inicialmente muteadas:

1. `Guitar MIDI - Original`;
2. `Guitar MIDI - Safe`;
3. `Guitar MIDI - Reconstructed`.

Una etapa posterior asignará un instrumento común o una ruta compartida para
escuchar exactamente las mismas regiones. La evaluación perceptual sigue
siendo humana y no se confunde con la verificación estructural del puente.
