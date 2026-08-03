# Propuestas supervisadas de mastering

`preview_mastering_proposal` convierte el control técnico de un WAV o FLAC en
una propuesta auditable. No persigue una cifra de loudness por rutina: sólo
propone ReaLimit cuando el true peak estimado supera la guía del perfil.

El punto de partida actual usa threshold y ceiling iguales. Así se crea margen
de pico sin agregar ganancia intencional. Para una entrega cercana a −14 LUFS,
la guía de −1 dBTP se traduce en un ceiling conservador de −1,5 dB, incluidos
0,5 dB de seguridad. Un master más fuerte usa −2,5 dB.

La aplicación exige:

- el ID exacto de una propuesta recalculada;
- la identidad SHA-256 del archivo analizado;
- creación explícita de ReaLimit o el GUID de una instancia existente;
- una única transacción reversible;
- relectura del nombre, GUID, estado y parámetros del plugin.

## Validación en REAPER 7.78

La referencia `Mi pequeño Sol.wav` produjo la propuesta
`d20ad7d7ad8d32cfac64fc9b`: threshold −1,50 dB, ceiling −1,50 dB y release
50,0 ms. El puente 0.11.1 creó ReaLimit en el master, leyó esos tres valores
desde el VST y marcó `state_verified: true`. Luego deshizo la transacción y
confirmó que el master volvió a cero FX.

La calibración recorre la escala realmente observable del VST porque algunos
parámetros no presentan extremos monotónicos. El release de 100 ms inicialmente
considerado no era representable por la instancia instalada; 50 ms sí lo es.

Esto verifica estado, no sonido. El paso siguiente para una canción real es
renderizar un candidato, volver a medir LUFS/true peak y comparar limitador
activado contra bypass mediante escucha humana.

Fuentes: [guía oficial de REAPER](https://www.reaper.fm/userguide.php) y
[API oficial de ReaScript](https://www.reaper.fm/sdk/reascript/reascripthelp.html).
