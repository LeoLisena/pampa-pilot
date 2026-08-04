# Benchmark de modelos en Cline

Esta prueba compara modelos dentro del cliente que se usará diariamente. Mide el
tiempo end-to-end, uso correcto de herramientas, continuidad, comprensión de la
arquitectura y respeto del modo read-only. No mide calidad musical.

## Iniciar

Con el modelo candidato cargado en LM Studio:

```powershell
.\scripts\cline-model-benchmark.ps1 `
    -Start `
    -Model "identificador/del-modelo" `
    -WorkingDirectory "C:\ruta\a\local-llm-daily"
```

El script guarda el estado inicial y copia un prompt estandarizado. Péguelo en
una **tarea nueva** de Cline y espere su bloque `RESULTADO`.

## Finalizar

```powershell
.\scripts\cline-model-benchmark.ps1 `
    -Finish `
    -RunId "id-mostrado-al-iniciar" `
    -Outcome pass `
    -ContinuityBreaks 0 `
    -ArchitectureScore 5 `
    -Notes "Completó todos los pasos sin asistencia"
```

Use `partial` si necesitó corrección o faltó evidencia y `fail` si abandonó la
tarea, inventó resultados o no pudo usar herramientas. Cada vuelta a un saludo,
pregunta genérica o pérdida del objetivo cuenta como una ruptura de continuidad.
`ArchitectureScore` va de 0 a 5 y se evalúa contra `docs/architecture.md`.

El puntaje máximo es 100: resultado 50, seguridad read-only 20, continuidad 20
y arquitectura 10. Los JSON y prompts quedan en
`.runtime/cline-model-evaluations/`, fuera de Git. Compare primero puntaje y
continuidad; use el tiempo para desempatar modelos igualmente fiables.
