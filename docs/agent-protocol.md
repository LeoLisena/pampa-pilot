# Protocolo entre PampaPilot y el cerebro

La frontera entre el LLM y la aplicación es `pampapilot-agent/1.0`. Es distinta
del IPC `0.1` entre Python y el Bridge Lua: un cambio de proveedor de IA no altera
el contrato con REAPER.

## Responsabilidades

- PampaPilot posee archivos, mediciones, conocimiento, estado de REAPER,
  políticas, aprobaciones, ejecución y verificación.
- El LLM recibe contexto seleccionado, interpreta intención y devuelve acciones
  tipadas. Nunca conoce rutas internas ni llama REAPER directamente.
- Los JSON Schema canónicos están en `schemas/agent/v1/`.

## Contexto híbrido

El primer turno recibe un resumen del proyecto y hasta cuatro fragmentos de
conocimiento recuperados de forma determinista. Los siguientes turnos reutilizan
la conversación de LM Studio y sólo anexan conocimiento relevante nuevo. La
búsqueda se cachea por contenido y se invalida al cambiar un archivo.

No se envía toda la base: cada fragmento incluye `knowledge_id`, título, etapa y
origen relativo para poder auditar el criterio usado.

## Solicitud de evidencia

Cuando la decisión necesita datos ausentes, el LLM puede devolver hasta cuatro
acciones `request_evidence` de estos tipos:

- `project_analysis`
- `track_analysis`
- `reaper_track_state`
- `fx_parameters`
- `knowledge`

PampaPilot agrupa las lecturas en una única respuesta y hace, como máximo, una
segunda inferencia. Una ronda de evidencia no puede contener mutaciones. Si el
modelo vuelve a solicitar datos o no produce JSON válido, no se ejecuta nada.

## Flujo

```text
usuario -> contexto + RAG -> LLM -> plan JSON
                              |-> request_evidence (opcional, una ronda)
plan -> validador determinista -> aprobación -> Bridge -> REAPER
     <- resultado tipado      <- verificación por relectura
```

El endpoint `GET /api/agent-protocol` publica versión, acciones y evidencias
admitidas para clientes locales o remotos.
