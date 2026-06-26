# draft1 — IEEE LaTeX Paper

**Title:** Empirical Analysis of Tilt-Angle Optimization for Solar Energy Harvesting in Bangalore (12.97°N)

## Files

| File | Description |
|------|-------------|
| `main.tex` | Full IEEE-format LaTeX source (IEEEtran `conference` class) |
| `write_main.py` | Helper script used to generate `main.tex` |

## How to Compile

Requires a LaTeX distribution (TeX Live / MiKTeX) with the following packages:
`IEEEtran`, `amsmath`, `graphicx`, `booktabs`, `hyperref`, `siunitx`, `cite`, `float`, `gensymb`, `microtype`

```bash
# Option 1 — pdflatex (two passes for citations and cross-references)
pdflatex main.tex
pdflatex main.tex

# Option 2 — latexmk (recommended, handles all passes automatically)
latexmk -pdf main.tex
```

> **Figures:** The paper references figures from `../graphs/` (the `graphs/` folder in the project root).
> `\graphicspath{{../graphs/}}` is set in the preamble.
> Compile from the `draft1/` directory so the relative path resolves correctly.

## Paper Structure

1. **Abstract** — Key findings summary (45.86% yield improvement at 36° vs 13°)
2. **Introduction** — Problem, motivation, 4 specific contributions
3. **Related Work** — Mathematical models, hardware studies, UHI effects, intraday behaviour
4. **System Architecture** — Sensor table (INA219, BH1750, DS18B20, MPU-6050), firmware, software stack
5. **Experimental Methodology** — Mathematical framework (thermal correction Eq. 1, normalised efficiency Eq. 2, cumulative energy Eq. 3), protocol, dataset table
6. **Results** — Aggregate comparison table, per-session breakdown table, 10 embedded figures from `graphs/`
7. **Discussion** — Geometric interpretation (solar noon calculation), thermal contribution, comparison with computational models, UHI implications, limitations
8. **Conclusion** — Summary + future work directions
9. **References** — 12 IEEE-format citations

## Key Quantitative Findings

| Metric | 13° | 36° | Improvement |
|--------|-----|-----|------------|
| Cumulative Energy (Wh) | 0.3172 | 0.4626 | **+45.86%** |
| Peak Power (W) | 0.056 | 0.088 | +57.1% |
| Normalised Efficiency (W/klux) | 2.43×10⁻⁴ | 4.61×10⁻⁴ | **+89.7%** |
| Avg. Panel Temperature (°C) | 46.01 | 38.52 | −7.49°C |
| Avg. Ambient Lux | 30,172 | 20,068 | — |
