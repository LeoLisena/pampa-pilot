# Interfaz web de PampaPilot

## Alcance de la primera versión

La interfaz reemplaza la navegación manual de `media/` y `sessions/` para el
flujo habitual. Permite:

- ver el proyecto, BPM, origen, letra, secciones y stems descubiertos;
- crear una canción cargando stems, MIDI, referencia y letra;
- configurar LM Studio sin escribir el token en archivos;
- conversar con el Productor IA usando contexto estructurado del proyecto;
- recibir planes tipados con aprobación manual o automática configurable;
- declarar por stem si proviene de Suno o de una grabación orgánica;
- abrir controles tipados de volumen, paneo, mute y solo para una pista real;
- previsualizar y aplicar filtros individuales o una cadena de FX nativos;
- ejecutar desde chat mezcla estática, filtros, buses de ambiente, vocal rider,
  volumen por secciones, estructura, MIDI, mastering, análisis y render;
- deshacer todas las transacciones de un plan y consultar la actividad.

Las propuestas libres del LLM siguen siendo deliberadamente **no ejecutables**.
Cuando el modelo devuelve una intención permitida, PampaPilot la vuelve a resolver
contra nombres, roles, GUID, estado actual y evidencia del motor. El texto del LLM
nunca se envía a REAPER. La interfaz manual y el chat comparten el mismo gateway
determinista, lectura posterior y Undo.

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
- aprobación manual, automática para riesgo bajo o automática total;
- token, que se conserva sólo en memoria hasta cerrar PampaPilot.

Opcionalmente, **Recordar token** guarda un blob cifrado por Windows DPAPI bajo
`.runtime/secrets/`. Sólo el mismo usuario de Windows puede descifrarlo. El token
en claro nunca forma parte de respuestas HTTP, logs ni archivos versionados.
La URL, modelo, autenticación, timeout y política de aprobación se guardan sin
secretos en `.runtime/web-settings.json` para sobrevivir a un reinicio.

La aprobación automática no desactiva validación ni verificación. El modo de
riesgo bajo permite ajustes reversibles como volumen, paneo y filtros conservadores.
El modo total también puede ejecutar automatizaciones, regiones y render, por lo
que está pensado para pruebas. La política predeterminada sigue siendo manual.

El adaptador usa la API nativa `/api/v1/models` y `/api/v1/chat`. En conversación
simple desactiva el razonamiento; en análisis musical lo habilita. Las órdenes
directas reciben un catálogo pequeño de nombres y roles para evitar latencia y
JSON incompleto. El LLM recibe un system prompt versionado, contexto sin rutas locales, letra, secciones e inventario de
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
6. En **Filtros individuales**, elegir EQ, compresor, gate, de-esser, resonancia,
   saturación o ReaTune y calcular sus parámetros antes de aplicar.
7. En **Cadena recomendada**, previsualizar la secuencia completa. Aplicar sólo se
   habilita si la pista y los FX existentes pudieron verificarse.
8. Usar **Deshacer última acción**; para un plan de chat revierte sus transacciones
   en orden inverso.

## Acciones disponibles por chat

- mezcla estática relativa o absoluta: volumen, paneo, mute y solo;
- EQ, compresión, gate, de-esser, resonancia dinámica, saturación y ReaTune;
- cadena de productor completa por pista;
- buses de reverb o delay y su envío;
- vocal rider para voz orgánica y volumen sutil por secciones;
- aplicación de regiones estructurales ya analizadas;
- limpieza/reconstrucción MIDI conservando originales;
- propuesta de mastering basada en el último QC;
- análisis técnico del proyecto y render candidato nuevo.

Una frase puede producir varias acciones. Los ajustes estáticos se agrupan en una
única transacción. Las acciones de un plan complejo se ejecutan secuencialmente y,
si una falla, PampaPilot intenta deshacer las anteriores antes de informar el error.
El render siempre se mantiene como acción terminal separada.

La cadena automática trata los stems de Suno de forma conservadora. Una toma orgánica
de voz o guitarra puede recibir puntos de partida para gate, EQ, compresión, de-esser o
control dinámico cuando las mediciones lo justifican. Toda la cadena se aplica en una
única transacción de REAPER.

## Mapa de funciones

La vista **Herramientas** diferencia:

- **Disponible offline**: ya puede usarse sin REAPER;
- **Pantalla + chat**: tiene un flujo manual y conversacional completo;
- **Disponible por chat**: usa el gateway tipado desde el Productor IA;
- **Motor listo**: la lógica y el Bridge existen, pero todavía se usará desde el agente
  o desde una futura pantalla guiada.

Este mapa evita confundir código ya implementado con controles todavía no expuestos.
La vista **Actividad** registra clasificaciones, aplicaciones y Undo durante el proceso
actual; no incluye secretos ni contenido del chat.
