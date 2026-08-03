# Compatibilidad mono por stem

`preview_mono_compatibility` compara la energía estéreo con la señal Mid
`(L+R)/2` sin renderizar ni escribir audio. La correlación se conserva como una
observación, pero no decide por sí sola: el informe mide retención mono en
bloques activos de 100 ms, proporción de bloques con cancelación severa y
retención en siete bandas entre 20 Hz y 20 kHz.

La política versionada distingue `compatible`, `review` y
`severe_cancellation`. Sólo los dos últimos estados proponen una audición con
ancho reducido; nunca aplican el cambio. Para stems de Suno la postura permanece
`correct_observed_defect_only`, porque una imagen deliberadamente amplia no es
un defecto por sí misma.

## Validación real

El stem `Backing Vocals` de `Mi Pequeño Sol` tiene correlación −0,518, pero el
análisis más completo lo clasificó como compatible:

- retención mono mediana: −5,053 dB;
- percentil 10: −6,603 dB;
- cero bloques con cancelación severa;
- ninguna banda relevante por debajo del límite de retención.

Por lo tanto devuelve `no_change_recommended`: no conviene reducir su ancho con
la evidencia actual. La decisión artística puede revisarse escuchando el mix en
mono, pero PampaPilot no inventará una corrección basándose sólo en correlación.
