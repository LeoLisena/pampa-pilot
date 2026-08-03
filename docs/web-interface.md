# Interfaz web de PampaPilot

## Alcance de la primera versión

La interfaz reemplaza la navegación manual de `media/` y `sessions/` para el
flujo habitual. Permite:

- ver el proyecto, BPM, origen, letra, secciones y stems descubiertos;
- crear una canción cargando stems, MIDI, referencia y letra;
- configurar LM Studio sin escribir el token en archivos;
- conversar con el Productor IA usando contexto estructurado del proyecto;
- recibir propuestas que siempre requieren aprobación;
- declarar por stem si proviene de Suno o de una grabación orgánica;
- abrir controles tipados de volumen, paneo, mute y solo para una pista real;
- previsualizar y aplicar una cadena de FX nativos recomendada por el motor;
- deshacer la última transacción propia y consultar la actividad de la sesión.

Las propuestas libres del LLM siguen siendo deliberadamente **no ejecutables**:
no se confía en texto generado para modificar un DAW. Las acciones disponibles
desde el panel de cada stem usan, en cambio, contratos deterministas del motor,
GUID de pista, aprobación explícita, lectura posterior de REAPER y Undo.

## Arranque

```powershell
.\scripts\run-web.ps1
```

Luego abrir `http://127.0.0.1:8765`.

Para acceder desde otro equipo de la misma red:

```powershell
.\scripts\run-web.ps1 -ServeOnLocalNetwork
```

El modo LAN usa HTTP sin cifrado. Debe utilizarse sólo en una red privada y con
autenticación de LM Studio habilitada. Antes de una distribución pública se
agregará autenticación propia de PampaPilot y HTTPS mediante un proxy local.

## Cerebro local

En **Configuración** se definen:

- URL de LM Studio, por ejemplo `http://192.168.1.19:1234`;
- identificador del modelo, por ejemplo `google/gemma-4-31b`;
- seguridad con token (predeterminada) o servidor sin autenticación;
- tiempo máximo de generación, 180 segundos de forma predeterminada;
- token, que se conserva sólo en memoria hasta cerrar PampaPilot.

Opcionalmente, **Recordar token** guarda un blob cifrado por Windows DPAPI bajo
`.runtime/secrets/`. Sólo el mismo usuario de Windows puede descifrarlo. El token
en claro nunca forma parte de respuestas HTTP, logs ni archivos versionados.

El adaptador usa la API nativa `/api/v1/models` y `/api/v1/chat`. En conversación
simple desactiva el razonamiento; en análisis musical lo habilita. El LLM recibe un system
prompt versionado, contexto sin rutas locales, letra, secciones e inventario de
medios. Los WAV permanecen en el motor y no se envían al modelo conversacional.
El primer turno almacena una sesión local en LM Studio; los turnos siguientes
envían sólo el mensaje nuevo y `previous_response_id`. Si cambia el nivel de
contexto, PampaPilot agrega los nuevos datos dentro de la misma conversación.
Sólo al cambiar de proyecto crea otro chat; el navegador recuerda el identificador
de conversación asignado a cada canción.

## Análisis técnico desde la interfaz

**Analizar proyecto** ejecuta primero el motor determinista y local de PampaPilot:

1. mide cada WAV (LUFS, pico, dinámica, espectro, correlación y otras métricas);
2. aplica las reglas de diagnóstico según el origen declarado;
3. guarda `sessions/<canción>/analysis/song-diagnosis.json`;
4. actualiza el estado y los hallazgos de cada stem en la interfaz;
5. recién entonces entrega al LLM un resumen sin rutas ni hashes para su interpretación.

El reporte se invalida automáticamente cuando cambia un stem, el BPM o la clasificación
de origen. Un proyecto `mixed` sin origen por stem se analiza como `unknown`: el motor no
adivina qué pistas son Suno u orgánicas. El análisis nunca modifica REAPER y sus resultados
son observaciones técnicas que requieren escucha antes de tomar decisiones de mezcla.

La API correspondiente es `POST /api/projects/{project_name}/analysis`. Cuando aparece
un reporte nuevo, el chat conserva la conversación de la misma canción pero recibe una
actualización explícita de contexto, independientemente del LLM configurado.

## Flujo de prueba por stem

1. Abrir REAPER, cargar el proyecto correcto y ejecutar **PampaPilot: Start bridge**.
2. En la web, pulsar `▶` o `⋮` junto al stem.
3. Confirmar que el encabezado diga **Vinculada con REAPER**.
4. Definir el origen del stem. Al cambiarlo, ejecutar otra vez **Analizar proyecto**.
5. Para un ajuste fino, revisar volumen/paneo/mute y pulsar **Revisar y aplicar**.
6. Para filtros, pulsar **Generar propuesta**. La propuesta enumera cada FX y explica
   por qué lo sugiere. **Aplicar cadena aprobada** sólo se habilita si la pista y sus
   FX existentes pudieron verificarse.
7. Usar **Deshacer última acción** inmediatamente si el resultado no corresponde.

La cadena automática trata los stems de Suno de forma conservadora. Una toma orgánica
de voz o guitarra puede recibir puntos de partida para gate, EQ, compresión, de-esser o
control dinámico cuando las mediciones lo justifican. Toda la cadena se aplica en una
única transacción de REAPER.

## Mapa de funciones

La vista **Herramientas** diferencia:

- **Disponible offline**: ya puede usarse sin REAPER;
- **Disponible en esta pantalla**: tiene un flujo web completo;
- **Motor listo**: la lógica y el Bridge existen, pero todavía se usará desde el agente
  o desde una futura pantalla guiada.

Este mapa evita confundir código ya implementado con controles todavía no expuestos.
La vista **Actividad** registra clasificaciones, aplicaciones y Undo durante el proceso
actual; no incluye secretos ni contenido del chat.
