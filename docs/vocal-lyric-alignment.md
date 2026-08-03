# Alineación vocal reutilizable

`vocal_alignment.py` es un especialista opcional y de sólo lectura. Usa una
letra limpia, una propuesta estructural previa y el stem vocal aislado para
encontrar entradas de frases concretas. Conserva transcript, timestamps por
palabra, probabilidad, semejanza textual y confianza combinada en un JSON que
puede consumir cualquier cerebro.

Whisper se usa sólo para evidencia lingüística: texto, palabras, pausas y
duración de frases. No se interpreta como detector de notas, afinación, vibrato,
timbre ni dinámica. Esos datos corresponderán a un futuro analizador de
performance vocal separado.

Consumidores posibles:

- fine-tuning de secciones;
- sincronización de letra y subtítulos;
- ubicación de entradas y punch-ins;
- comparación temporal de tomas;
- navegación por frases.

## CPU y GPU

El dispositivo predeterminado es `auto`. Si encuentra GPU NVIDIA compatible,
driver, cuBLAS y cuDNN locales, selecciona CUDA/float16; de lo contrario usa
CPU/int8 e informa el fallback. `--device cuda` falla explícitamente si falta un
requisito, mientras `--device cpu` fuerza portabilidad.

En Windows, `scripts/install_cuda_runtime.py` descarga archivos oficiales de
NVIDIA con versiones y SHA-256 fijados, valida cada archivo y extrae únicamente
dentro de `.runtime/cuda`. No instala drivers ni modifica el sistema. Los
binarios no se versionan.

```powershell
python scripts/install_cuda_runtime.py
python scripts/align_vocal_lyrics.py vocal.wav lyric-clean.txt `
  base-structure.json vocal-alignment.json --device auto --language es
```

## Política de aplicación

Sólo se acepta un match de frase con confianza mínima 0,70. Si el inicio queda
a 250 ms o menos de un downbeat, se conserva el downbeat. Si la voz empieza
antes como pickup, se conserva el timestamp de frase para no cortar la primera
palabra. Un resultado de baja confianza no modifica la propuesta.

En `Mi Pequeño Sol`, Faster-Whisper large-v3 ejecutado en la RTX 3090 reconoció
ambos precoros completos con confianza 0,979. El primero se conserva en 45,76 s
y el segundo se ajusta a 113,21 s.
