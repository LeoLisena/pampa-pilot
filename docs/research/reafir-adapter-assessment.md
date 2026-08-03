# Evaluación del adaptador ReaFIR

## Ecosistema revisado

Los MCP de REAPER revisados sólo ofrecen operaciones genéricas para agregar FX
y escribir parámetros por índice. Total REAPER MCP incluso incluye ReaFIR en
una prueba de cadena, pero no configura reducción de ruido ni verifica su estado.

El hallazgo específico fue
[Remove Low-End Rumble and Background Noise](https://github.com/darkstardevx/REAPER_Scripts/blob/reapack-index/Scripts/ReaScripts/Tracks/RemoveLow-EndRumbleAndBackgroundNoise/RemoveLow-EndRumbleAndBackgroundNoise.lua),
publicado con licencia MIT. Su idea útil es separar dos operaciones: ReaEQ para
rumble y ReaFIR en modo subtract para ruido continuo.

No se copiará literalmente porque el script:

- supone que los parámetros 0 y 1 corresponden a modo y aprendizaje;
- no descubre nombres, identificadores ni valores formateados;
- no verifica la lectura posterior;
- aprende mientras reproduce sin exigir un tramo que contenga sólo ruido;
- aplica un pasa-altos fijo a 100 Hz independientemente de la fuente;
- puede agregar procesadores repetidos por cada ítem seleccionado.

El flujo de restauración de
[Hipare Reaper Agent](https://github.com/Hipare/Hipare-Reaper-agent/blob/main/knowledge/knowledge/workflows/audio-restoration.md)
aporta una precaución válida: aprender el perfil únicamente sobre ruido aislado
y evitar reducciones agresivas que produzcan artefactos acuosos o robóticos.
Se usa como referencia conceptual, no como código de ejecución.

## Decisión de PampaPilot

1. agregar y retirar ReaFIR por GUID;
2. descubrir en vivo parámetros, nombres y valores formateados;
3. habilitar modo subtract sólo mediante un adaptador tipado;
4. capturar un perfil únicamente sobre un intervalo aprobado;
5. detener el aprendizaje y verificar el estado final;
6. diferenciar grabaciones orgánicas, stems de Suno y fuente desconocida;
7. separar verificación de estado, medición de señal y escucha perceptual.

La instalación local confirmó `VST: ReaFir (FFT EQ+Dynamics Processor)
(Cockos)` desde el plugin nativo `reafir.dll` de REAPER 7.78/x64.

## Descubrimiento en REAPER 7.78

La instancia de prueba expuso once parámetros. Los relevantes para esta
decisión fueron:

| Índice | Identificador público | Lectura inicial |
|---:|---|---:|
| 0 | `Show analysis` | `1` |
| 1 | `Processing mode` | `0` |
| 2 | `Gate Floor` | `-inf` |
| 3 | `Compressor Ratio` | `1.00` |
| 4 | `Output Gain` | `+0.0` |
| 5 | `Analysis Floor` | `-90.0` |
| 6 | `Legacy Compatibility Modes` | `0` |
| 7 | `Adjustment Graph Offset` | `+0.0` |

El muestreo de sólo lectura del índice 1 produjo únicamente `0` y `1`. La
inspección visual posterior mostró, al mismo tiempo, `Mode: EQ`, `Show analysis`
activado y `Reduce artifacts (less effective)` desactivado. Por correspondencia
de estado, el parámetro denominado genéricamente `Processing mode` representa
la casilla de reducción de artefactos; no representa el selector principal de
modo.

La interfaz también mostró FFT 4096, calidad máxima, medición Average, piso de
análisis -90 dB, salida 0 dB y la curva plana. El selector principal
EQ/Gate/Compressor/Convolve/Subtract y el perfil espectral quedan almacenados en
estado privado del plugin, fuera de los parámetros VST enumerables.

Esto refuta para esta versión la suposición del script externo que escribe los
índices 0 y 1 para seleccionar Subtract y aprender ruido. PampaPilot conserva
por ahora únicamente el alta, retirada y descubrimiento verificables. El flujo
de denoise se implementará sólo mediante un estado reproducible y releíble, o
como procesamiento offline separado que preserve el original.
