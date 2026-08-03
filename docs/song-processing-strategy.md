# Estrategia de procesamiento por stem

`preview_song_processing_strategy` convierte el diagnóstico completo en una
estrategia conservadora y no ejecutable. La procedencia se decide por stem, por
lo que una sesión puede combinar una base de Suno con voz, guitarra o cuerdas
orgánicas.

## Política

- `suno_stems`: conserva el procesamiento existente y no propone EQ o
  compresión por rutina;
- `organic_multitrack`: permite candidatos de audición sólo cuando un hallazgo
  de señal activa una regla versionada;
- `unknown`: exige clasificar la procedencia antes de recomendar procesamiento
  dependiente de la fuente.

La primera versión incluye perfiles para voz principal, coros, bajo, batería,
guitarra y cuerdas. Una dinámica orgánica amplia puede activar ReaComp como
punto de partida; en voces, la energía baja observada puede habilitar una
audición de pasa-altos. Tener un perfil disponible no basta para usarlo.

## Garantías y límites

La salida incluye identidad del audio, hallazgos activadores, reglas, valores
iniciales y un `strategy_id` determinista. Siempre devuelve `execute: false`.
No abre ni modifica REAPER, y no confunde medición de señal con aprobación
perceptual. Las cadenas propuestas continúan requiriendo A/B a volumen igualado
y ajuste fino humano.

Cada stem incluye además `problem_routes`: una ruta reutilizable desde el
hallazgo hacia el siguiente análisis o procesador apropiado. El clipping deriva
a reemplazo o reexportación —ningún filtro recupera muestras destruidas—; la
sibilancia a la propuesta de de-esser; una concentración de presencia al
analizador dinámico de resonancias; la variación orgánica amplia a
automatización/compresión; y los pasajes silenciosos medibles a una evaluación
conservadora de gate. Estas rutas nunca ejecutan y conservan para Suno la postura
`correct_observed_defect_only`.

## Validación con Mi Pequeño Sol

Los 12 stems actuales se declararon como procedentes de Suno. La estrategia
`48492e98b3f8d19a1177fbc4` clasificó los 12 como
`preserve_existing_processing`, produjo cero candidatos de procesamiento y
devolvió `no_processing_recommended`. Esto confirma que disponer de presets no
provoca procesamiento rutinario sobre la maqueta generada.
