# Estructura de canción guiada por letra

PampaPilot 0.26.0 acepta una letra `.txt` opcional junto a los stems. Las
etiquetas reconocidas (`Intro`, `Verse`, `Pre-Chorus`, `Chorus`, `Bridge`,
`Final Chorus`, `Outro` y equivalentes en español) determinan el orden y los
nombres. Las restantes líneas completas entre corchetes se conservan como
notas de arreglo; el texto libre se conserva como letra aunque esté repetido o
corrupto por una regeneración de Suno.

La letra no fija tiempos. El motor analiza cambios de energía, ataques, centro
espectral, ancho espectral y armonía del mix. Combina esa novedad con una forma
temporal previa según cada clase de sección y, cuando hay BPM, evalúa candidatos
sobre la grilla de compases. La propuesta contiene hashes de ambos archivos,
versión del algoritmo, evidencia por límite y un `structure_id` determinista.

Cuando se proporciona el stem vocal, el primer bloque vocal sostenido ancla el
final de una `Intro` sobre la grilla de compases. Esto evita que una transición
instrumental temprana se confunda con el comienzo de la primera estrofa.

`preview_song_structure` nunca modifica REAPER. Tras aprobación,
`apply_project_song_structure` recalcula la propuesta y crea regiones contiguas
con nombres limpios, colores por función y lectura posterior exacta. Una marca
Unicode invisible conserva la identidad técnica sin ocupar espacio visual. Al
recalcular puede reemplazar exclusivamente regiones propias anteriores; no
borra marcadores del usuario y agrupa todo en una única transacción undo.

Los nombres y el orden tienen evidencia explícita de la letra. Los tiempos son
estimaciones y requieren revisión visual/auditiva; el motor nunca declara una
evaluación perceptual automática.

## Mi Pequeño Sol

`lyric.txt` produjo diez secciones válidas pese a la corrupción de varias
palabras: Intro, Verse 1, Pre-Chorus, Chorus, Verse 2, Pre-Chorus, Chorus,
Bridge, Final Chorus y Outro. Sobre el render del proyecto a 85 BPM, la propuesta
La primera propuesta evidenció un límite incorrecto de Intro al usar sólo el
mix. El stem `10 Vocals.wav` midió su primera voz sostenida a 26,2 s y la
propuesta corregida `cc11da6a89881c49ed00a082` fijó `Intro → Verse 1` a
25,412 s, sobre la grilla de 85 BPM. Los demás límites permanecen entre 42,353 s
y 223,059 s. La sustitución visual en REAPER continúa pendiente de validación.
