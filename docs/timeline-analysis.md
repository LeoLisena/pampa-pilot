# Motor reutilizable de análisis temporal

`src/pampapilot/timeline_analysis.py` analiza stems WAV/FLAC alineados fuera del
DAW. Infere roles por nombre sin depender del número de pista, admite una grilla
4/4 calculada desde BPM o downbeats externos, y produce por intervalo:

- RMS y proporción activa;
- fuerza de ataques;
- centro, ancho y rolloff espectral;
- chroma normalizado de doce clases;
- embedding robustamente normalizado;
- cambio por stem y por rol, delta de energía y consenso multistem.

Las dimensiones constantes o silenciosas aportan cero; no se amplifica ruido
numérico. También se verifica que las duraciones de stems difieran menos de
100 ms, evitando comparar pistas desalineadas.

El informe declara explícitamente que sus valores son observaciones y no
decisiones de mezcla. Consumidores previstos: estructura, balance estático,
procesamiento dinámico, EQ, detección de silencios/fugas y automatización.

El CLI reutilizable escribe un artefacto JSON sin abrir REAPER:

```powershell
python scripts/analyze_timeline.py "media/inbox/stems/Canción" `
  "sessions/Canción/analysis/timeline.json" --bpm 85 `
  --specialist-analysis "sessions/Canción/analysis/all-in-one-structure.json"
```
