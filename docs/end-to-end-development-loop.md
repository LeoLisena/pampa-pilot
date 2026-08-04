# Ciclo end-to-end de desarrollo con el usuario

Este documento define la dinámica habitual de PampaPilot para cualquier agente
de desarrollo. El objetivo es conservar una colaboración continua: el agente
implementa y prueba; el usuario valida el comportamiento real y devuelve
feedback; el agente corrige hasta cerrar la funcionalidad.

## 1. Continuidad de la tarea

- Antes de actuar, leer `AGENTS.md`, el pedido actual, `git status`, el diff y la
  documentación más cercana a la funcionalidad.
- Mantener un plan/TODO breve durante trabajos de varios pasos.
- Mientras existan cambios o validaciones pendientes, continuar la tarea actual.
- No volver a un saludo genérico ni preguntar qué hacer después de cada tool.
- Preguntar sólo ante un bloqueo real, una decisión material o una acción externa
  riesgosa que requiera autorización.

## 2. Implementación

- Trabajar normalmente en `local-llm/daily`; reservar worktrees aislados para
  experimentos, cambios riesgosos o tareas no relacionadas.
- Comprender el flujo completo antes de modificar una frontera entre Python,
  web, protocolo del agente, MCP y bridge Lua.
- Reutilizar contratos, validadores, análisis y conocimiento existentes.
- Agregar tests de regresión y casos negativos junto con la implementación.
- No declarar éxito por haber creado archivos: integrar el cambio en todos los
  componentes que realmente lo consumen.

## 3. Verificación automática

1. Ejecutar tests focalizados durante la iteración.
2. Revisar el diff y buscar archivos accidentales o datos sensibles.
3. Ejecutar `scripts/validate.ps1` antes de entregar la funcionalidad.
4. Informar comandos ejecutados, resultados y advertencias restantes.

Los tests offline no prueban por sí solos REAPER, audio, UI ni red.

## 4. Integración local cuando corresponda

Según el alcance, el agente puede:

- iniciar o reiniciar el servidor web mediante los scripts versionados;
- comprobar endpoints, estado del bridge y rutas efectivas;
- instalar o sincronizar el loader/bridge mediante los scripts del proyecto;
- leer logs del servidor, IPC y bridge para diagnosticar fallos;
- verificar que la versión reportada por la web y el bridge sea la esperada.

No operar la interfaz de REAPER ni modificar un proyecto real sin que el pedido
actual autorice una prueba en vivo. Nunca confundir una simulación offline con
una validación real en el DAW.

## 5. Prueba manual con el usuario

- Proponer una sola prueba concreta y breve, indicando qué abrir, qué acción
  ejecutar y qué resultado observar.
- Esperar la observación del usuario; no asumir que funcionó.
- Usar capturas, mensajes, logs y percepción auditiva informados por el usuario
  como evidencia, distinguiendo claramente lo técnico de lo subjetivo.
- Si el usuario detecta un problema, reproducirlo de forma segura, corregirlo,
  agregar una regresión cuando sea posible y repetir la validación.

## 6. Cierre e integración

La tarea termina sólo cuando:

- la implementación está completa en todos los componentes necesarios;
- los tests automáticos relevantes pasan;
- la prueba manual requerida fue realizada o quedó explícitamente pendiente;
- se incorporó el feedback recibido;
- el diff fue revisado y no contiene archivos ajenos.

No hacer commit, push, merge ni borrar ramas sin autorización explícita. El
informe final debe permitir que Codex supervise el cambio: objetivo, archivos,
decisiones, pruebas, evidencia manual y riesgos restantes.
