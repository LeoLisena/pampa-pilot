# Control técnico del master para distribución

`preview_master_delivery_qc` analiza el WAV o FLAC que realmente se entregaría.
No modifica el archivo ni REAPER. Complementa —no reemplaza— la lectura del
proyecto: REAPER describe pistas, FX, ruteo y render; el archivo final demuestra
qué señal se produjo.

## Perfil inicial: Spotify

El perfil versionado registra la guía oficial vigente: normalización normal a
−14 LUFS integrados, true peak recomendado por debajo de −1 dBTP y, para masters
más fuertes que −14 LUFS, por debajo de −2 dBTP. Estos valores permiten simular
la reproducción y advertir riesgos; no obligan a masterizar toda música a una
sonoridad idéntica.

El informe mide:

- LUFS integrados y sample peak;
- true peak estimado mediante sobremuestreo polifásico 4×;
- clipping de muestras, canales, sample rate, formato y subtipo;
- escenarios de normalización normal, fuerte y silenciosa;
- límites de la medición y verificaciones todavía pendientes.

El true peak local es orientativo. El render de distribución debe confirmarse
con un medidor conforme a estándar, una prueba de codificación y escucha humana.

## Línea base de Mi Pequeño Sol

La referencia de Suno —no un master final renderizado desde REAPER— produjo el
informe `d2800ed1a5ea8113ef4e5753`: WAV PCM de 16 bits, 48 kHz, estéreo,
−14,40 LUFS integrados, sample peak de −0,18 dBFS y true peak estimado de
−0,18 dBTP. No contiene muestras a 0 dBFS, pero el margen de true peak queda por
debajo de la recomendación del perfil y requiere revisión en el master final.
