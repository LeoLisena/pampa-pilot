# Primera prueba de integración

Fecha: 2026-08-02

Entorno:

- REAPER 7.78/x64 para Windows;
- puente Productor Musical 0.1.0;
- MCP Python SDK 2.0.0;
- proyecto desechable `fixtures/empty-smoke-test.rpp`.

Recorrido ejecutado contra el puente instalado en la carpeta de recursos de
REAPER:

1. `health_check` confirmó versión, proyecto y referencia de sesión.
2. Se leyó un proyecto con cero pistas.
3. Se creó `Codex POC - prueba reversible` y se obtuvo su GUID.
4. Se escribió paneo `-0.35`.
5. Dos lecturas independientes devolvieron `-0.35`.
6. Se deshizo la transacción de paneo.
7. Se deshizo la creación de pista.
8. Una lectura final confirmó cero pistas.

Resultado final:

```json
{
  "ok": true,
  "reaper_version": "7.78/x64",
  "bridge_version": "0.1.0",
  "pan_verified": -0.35,
  "undo_verified": true,
  "final_track_count": 0
}
```

Incidencias útiles encontradas durante la prueba:

- una tabla Lua vacía se serializaba como arreglo JSON; las respuestas fallidas
  ahora omiten `result` y conservan un error estructurado;
- una pista nueva puede informar `I_PANMODE=-1`, que significa modo heredado del
  proyecto; se admite junto con clásico y balance;
- reiniciar un script diferido desde otra invocación no es fiable para el flujo
  de desarrollo; la prueba definitiva se hizo en una instancia limpia;
- la ventana de evaluación de REAPER no impide que el puente procese comandos,
  aunque sí bloquea interacciones visuales hasta pulsar `Still Evaluating`.

