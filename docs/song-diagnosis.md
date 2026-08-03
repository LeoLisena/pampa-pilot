# Diagnóstico de canción

`diagnose_song` reanaliza todos los WAV y construye un diagnóstico de mezcla sin
escribir archivos ni modificar REAPER. La procedencia se define por stem, porque
una misma producción puede combinar una maqueta de Suno con voz, guitarra o
cuerdas grabadas orgánicamente.

## Procedencia y postura

- `suno_stems`: preservar el procesamiento existente y corregir sólo problemas
  observables; una dinámica estrecha no autoriza más compresión.
- `organic_multitrack`: revisar captura, ruido, dinámica y resonancias antes de
  las decisiones estéticas.
- `unknown`: medir y pedir procedencia antes de aplicar reglas dependientes de la
  fuente.

La herramienta recibe una procedencia predeterminada y excepciones por nombre
de pista. Nunca identifica la procedencia sólo por el sonido.

## Observaciones nuevas

Además de LUFS, picos, RMS, clipping, silencios, DC y estéreo, el analizador WAV
calcula:

- percentiles de RMS durante audio activo y su dispersión dinámica;
- energía relativa en siete bandas entre 20 Hz y 20 kHz;
- centroide y planitud espectral;
- concentración temporal en la zona 5–10 kHz;
- energía por debajo de 100 Hz.

Los hallazgos distinguen hechos de alta confianza —por ejemplo clipping— de
candidatos que requieren escucha, como sibilancia o exceso de graves.

## Relaciones

Los hashes detectan duplicados exactos. La similitud espectral y la actividad
sirven sólo para priorizar pares que conviene revisar. No se presentan como
prueba de enmascaramiento: faltan contexto musical, nivel relativo y evaluación
perceptual.

## Primera ejecución real

Los 12 stems actuales de `Mi Pequeño Sol` se diagnosticaron como material de
Suno, sin excepciones orgánicas. El análisis no escribió archivos ni modificó
REAPER y produjo:

- cero duplicados exactos;
- un hallazgo de prioridad media: correlación estéreo negativa en
  `Backing Vocals`, derivado correctamente a comprobación mono;
- ocho pares de similitud espectral para revisión, todos marcados como
  candidatos de baja confianza y no como enmascaramiento demostrado.

Los pares principales fueron Synth/Guitar, variantes de Drums y Bass/Drums. El
resultado es coherente con la política conservadora: no recomendó compresión ni
EQ por rutina sobre los stems generados.

La comprobación especializada posterior midió la cancelación por tiempo y por
bandas. Clasificó `Backing Vocals` como compatible y devolvió
`no_change_recommended`; la correlación negativa no produjo por sí sola una
reducción de ancho.
