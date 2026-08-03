# Producer chain por pista

## Objetivo

Transformar adaptadores aislados en una decisión de productor reproducible. El
plan analiza el WAV, considera rol y procedencia, consulta los FX reales y
selecciona únicamente candidatos de audición compatibles.

## Orden

1. ReaGate para limpieza con evidencia en fuentes orgánicas.
2. ReaEQ para limpieza tonal de perfiles orgánicos.
3. ReaXcomp para una resonancia dinámica demostrada.
4. ReaComp para control general orgánico.
5. ReaXcomp de-esser cuando una voz orgánica muestra sibilancia intermitente.
6. JS Multi Waveshaper sólo si se solicita la etapa artística.

Suno preserva su procesamiento de origen: no recibe Gate, EQ, compresión o
de-esser por rutina. Puede recibir una resonancia con evidencia y parámetros
más suaves. Fuente desconocida no recibe cadena.

## Seguridad

El `chain_id` incluye SHA-256, pasos, parámetros y FX existentes. La aplicación
recalcula todo antes de aceptar la aprobación. Cada FX se identifica por GUID,
la cadena debe conservar orden creciente y cualquier fallo revierte el bloque
entero. FX ajenos no se eliminan ni reordenan.

Una ReaXcomp existente se considera ambigua porque su nombre no revela si fue
configurada como de-esser o resonancia. El plan se bloquea en lugar de
sobrescribirla. Las instancias únicas de ReaEQ, ReaComp, ReaGate o Waveshaper
pueden reutilizarse por su GUID explícito.

## Alcance actual

Vocal rider, buses de ambiente y A/B con loudness igualado se declaran como
etapas diferidas. Coordinarlas será el siguiente nivel del flujo, pero no deben
simularse como simples inserciones de FX.

En `3 Guitar.wav`, la cadena Suno actual conserva ReaFIR y propone únicamente
la resonancia dinámica 165,7-331,5 Hz. El plan no agrega EQ, compresión, Gate ni
saturación por rutina.

## Validación en vivo

El puente 0.24.0 aplicó la cadena `cffa42fdf5eb81bc6db79bfd` a Guitar. ReaFIR
conservó GUID e índice 0; la ReaXcomp creada ocupó índice 1 y sus 51 parámetros
coincidieron con el paso aprobado. La acción devolvió un solo ID transaccional.

Una lectura independiente confirmó orden e identidades. El undo del bloque
retiró ReaXcomp y restauró `fx_count=1`, volumen -7 dB, paneo central y estado
de automatización. El proyecto conservó 14 pistas y 85 BPM. Esta prueba valida
la orquestación de un paso; todavía falta una toma orgánica que produzca tres o
más pasos para probar el rollback conjunto en una cadena larga.
