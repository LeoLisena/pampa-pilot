# Candidatos de master con procedencia verificable

`render_and_verify_master_candidate` automatiza el tramo que antes quedaba
fuera del control de PampaPilot:

1. exige un proyecto REAPER guardado y detiene el transporte si es necesario;
2. acepta únicamente un WAV nuevo dentro de `sessions/`;
3. configura master mix estéreo, proyecto completo, sample rate explícito,
   WAV de 24 bits, sin normalización, sin dither y sin segunda salida;
4. comprueba que `RENDER_TARGETS` resuelva exactamente ese archivo;
5. ejecuta la acción nativa de render con cierre automático, sin depender de
   que REAPER guarde estadísticas internas;
6. verifica que el WAV exista y contenga datos;
7. calcula inmediatamente SHA-256, LUFS, picos y controles de distribución.

El resultado incluye el ID de la solicitud y transacción, la identidad y contador
de cambios del proyecto, los FX del master, los ajustes efectivos, la acción
nativa utilizada, las estadísticas de REAPER, el tamaño y hash del archivo y el
informe técnico. Por eso puede marcar
`render_provenance_verified: true`: el mismo flujo configuró, ejecutó, observó
y midió ese destino único.

Después del análisis, PampaPilot restaura explícitamente el snapshot anterior y
relee cada ajuste. No depende de Undo, porque el render nativo o una ventana
modal pueden alterar su historial. Restaurar la configuración no elimina el WAV
ya generado. PampaPilot nunca sobrescribe un candidato existente.
El archivo tampoco se considera master aprobado hasta completar escucha humana,
comparación con bypass y prueba de codificación.

## Validación integrada

El 3 de agosto de 2026 se completó una prueba real de extremo a extremo con
REAPER 7.78 y el puente 0.12.2. El flujo produjo un WAV estéreo PCM de 24 bits a
48 kHz, enlazó el archivo con la solicitud de render y verificó su SHA-256. El
análisis midió -20.17 LUFS-I, -5.24 dBFS de pico, -5.13 dBTP estimado y cero
muestras a 0 dBFS. Después se restauraron los ajustes anteriores y se eliminó
por GUID únicamente el ReaLimit temporal; la relectura final confirmó destino
de render vacío y cero FX en el master.

La prueba también demostró por qué las estadísticas internas son opcionales:
si su preferencia global está desactivada, PampaPilot no la modifica ni abre su
consulta. La verificación principal proviene del archivo renderizado y medido.

La implementación sigue las propiedades `RENDER_*`, `RENDER_TARGETS` y
`RENDER_STATS` documentadas en la
[API oficial de ReaScript](https://www.reaper.fm/sdk/reascript/reascripthelp.html).
