# Estructura de canción guiada por letra y stems

El motor 0.2 separa dos responsabilidades. `timeline_analysis` mide cada stem
alineado por compás; `song_structure` consume esas observaciones para proponer
regiones. El análisis no depende de REAPER y puede reutilizarse después para
balance, dinámica, EQ, silencios, automatización y diagnóstico.

Las etiquetas reconocidas en la letra (`Intro`, `Verse`, `Pre-Chorus`,
`Chorus`, `Bridge`, `Final Chorus`, `Outro` y equivalentes en español) fijan el
orden semántico. Las notas entre corchetes se conservan como intención de
arreglo y la letra libre se conserva incluso si Suno la regeneró con palabras
duplicadas o dañadas. La letra orienta; nunca inventa timestamps.

El parser clasifica cada entrada como `clean`, `uncertain` o `damaged`. La ruta
normal, optimizada para letras limpias, usa cantidad de frases y consistencia
textual entre precoros/estribillos repetidos. Si detecta duplicaciones, fragmentos
pegados o repeticiones incoherentes, desactiva esa confianza léxica y conserva
sólo la secuencia de tags; el audio pasa a dominar el timing.

## Evidencia temporal

La ruta de máxima precisión combina:

1. downbeats y macrosegmentos de un especialista externo compatible;
2. energía, ataques, centro/ancho/rolloff espectral, actividad y chroma de cada
   stem por intervalo musical;
3. consenso de cambios entre voz principal, coros, batería, bajo e instrumentos
   armónicos;
4. autosimilitud entre secciones repetidas, especialmente los dos precoros y
   las dos estrofas;
5. restricciones de factibilidad derivadas de las frases de la letra: por
   ejemplo, cuatro líneas de precoro no pueden colapsar en dos compases por un
   fill aislado.

El modelo externo es una segunda opinión de sólo lectura. Sus pesos y binarios
no forman parte de PampaPilot y el flujo básico continúa funcionando sin ellos.
Los especialistas jamás escriben en REAPER; sólo el adaptador Lua autorizado
puede materializar una propuesta aprobada.

Cada límite devuelve fuente, confianza, consenso multistem, cambios por rol y
detalles de selección. `structure_id` incluye hashes de audio, letra, stems,
análisis especialista y versión del algoritmo, por lo que una aprobación vieja
no puede aplicarse silenciosamente a evidencia nueva.

## Aplicación y seguridad

`preview_song_structure` nunca modifica REAPER. `apply_project_song_structure`
recalcula la propuesta aprobada y crea regiones contiguas, coloreadas y
reversibles. Una marca Unicode invisible conserva identidad técnica sin ensuciar
el nombre visible. Al recalcular sólo reemplaza regiones propias anteriores;
conserva los marcadores del usuario y agrupa la operación en una transacción
undo.

## Mi Pequeño Sol

La letra declara diez secciones. All-In-One ONNX detectó 85 BPM, downbeats y los
cambios macro. El análisis de los doce stems y la repetición entre ciclos
produjeron la propuesta limpia `511c8d6bcae7dfadf02e77c2`:

| Sección | Inicio (s) | Evidencia principal |
|---|---:|---|
| Intro | 0.00 | inicio |
| Verse 1 | 26.01 | voz + especialista |
| Pre-Chorus | 45.76 | transición rítmica + repetición |
| Chorus | 59.88 | especialista + entrada de coros |
| Verse 2 | 93.77 | especialista |
| Pre-Chorus | 110.71 | repetición + transición multistem |
| Chorus | 127.65 | especialista + coros |
| Bridge | 150.24 | salida del segundo chorus |
| Final Chorus | 186.93 | especialista |
| Outro | 220.82 | salida del final chorus + caída vocal |

Los nombres y el orden tienen evidencia explícita de la letra; los tiempos son
estimaciones de alta confianza, no una escucha humana. La revisión visual y
auditiva sigue siendo la validación final.
