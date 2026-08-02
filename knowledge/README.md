# Base de conocimiento musical

Esta carpeta no será una enciclopedia ni un único archivo de consejos. Contendrá
reglas pequeñas, citables y recuperables según el contexto de la sesión.

Una regla útil debe indicar:

- qué problema intenta resolver;
- en qué etapa aplica: edición, arreglo, mezcla o mastering;
- condiciones observables que la activan;
- acción sugerida, nunca una orden incondicional;
- excepciones y riesgos;
- cómo comprobar si ayudó;
- fuentes y fecha de revisión;
- nivel de confianza.

## Organización prevista

```text
knowledge/
  editing/
  arrangement/
  mixing/
  mastering/
  midi-cleanup/
  genres/
  references/
```

Las reglas generales y las preferencias del usuario se guardarán por separado.
Una preferencia estética no debe presentarse como hecho técnico. Tampoco se
automatizará una regla sólo porque exista en esta carpeta: el orquestador debe
compararla con el estado real y registrar el motivo de su aplicación.

## Plantilla de una regla

```yaml
id: mixing.example.short-id
title: Título legible
stage: mixing
problem: Qué síntoma intenta resolver
conditions:
  - medición o evidencia necesaria
suggestion:
  action: acción conceptual, no comando de REAPER
  range: rango prudente si corresponde
exceptions:
  - cuándo no aplicarla
verification:
  - qué volver a medir o escuchar
sources:
  - title: Fuente primaria o bibliografía reconocida
    url: https://...
confidence: draft
reviewed_at: YYYY-MM-DD
```

La carga inicial se hará después del recorrido técnico del MVP. Así podremos
probar cada regla contra fixtures de audio/MIDI en lugar de acumular consejos que
el sistema todavía no sabe observar ni validar.

