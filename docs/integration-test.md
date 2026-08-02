# Primera prueba de integración

Fecha: 2026-08-02

Entorno:

- REAPER 7.78/x64 para Windows;
- puente PampaPilot 0.1.0;
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

## Primera mezcla estática real

Sobre `Mi Pequeño Sol.rpp`, el puente 0.2.0 leyó y validó 12 pistas a 85 BPM.
Después se aplicaron volumen, paneo y mute mediante una sola transacción:

- las 12 pistas quedaron en `-6 dB` y paneo central;
- `Drums 1` y `Drums 2` quedaron muteadas como versiones alternativas;
- `Drums OK 1` y `Drums OK 2` permanecieron activas;
- una lectura independiente confirmó los 12 estados escritos.

La suma flotante equivalente, todavía sin FX ni mastering, midió:

```json
{
  "integrated_lufs": -20.4015,
  "sample_peak_dbfs": -5.9581,
  "samples_at_or_above_0_dbfs": 0,
  "stereo_correlation": 0.7838
}
```

La transacción permanece reversible y el proyecto no se guarda hasta completar
la primera evaluación auditiva.
