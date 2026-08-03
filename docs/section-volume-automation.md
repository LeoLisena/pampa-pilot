# Volumen opcional por secciones

`preview_section_volume_automation` genera movimientos relativos de volumen a
partir de regiones estructurales ya aprobadas, el rol de la pista y su origen. No
analiza otra vez el audio ni modifica REAPER. Es una ayuda artística pequeña, no
un objetivo de loudness y no supone que toda sección necesite distinto volumen.

La propuesta queda desactivada por defecto. Para stems de Suno se usa la mitad de
la intensidad prevista para una grabación orgánica, porque esos stems ya traen
balance y dinámica procesados. Los cambios se limitan a 0,50 dB para Suno y 0,75
dB para fuentes orgánicas, con rampas lineales de 100 ms por defecto.

`apply_section_volume_automation` recalcula la propuesta y exige su
`approved_proposal_id`. El puente 0.27.0 crea la envolvente de volumen sólo cuando
es necesario, rechaza cualquier rango que ya contenga automatización y verifica
por lectura posterior tiempo, ganancia, forma y tensión de cada punto. Toda
aplicación es una transacción reversible con Undo.

La evaluación final sigue siendo auditiva y preferentemente A/B con volumen
igualado. Si la energía de las secciones no mejora, se deshace la transacción y
se conserva la mezcla estática.
