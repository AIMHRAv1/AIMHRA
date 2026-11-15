# OCR unit policy

How the OCR layer handles measurement units. Goal: **never silently convert**;
ambiguous values are amber-flagged with suggestions; the operator confirms
everything.

## Temperature

| situation | behavior |
|---|---|
| explicit `C` / `°C` on the line AND value is a plausible Celsius reading (30–45) | converted to Fahrenheit (`mlcore`-style °F), no warning |
| explicit `C` / `°C` but implausible as Celsius (e.g. `380 °C`) | **not converted**; value kept, flagged red |
| explicit `F` / `°F` | kept as-is |
| **no unit** | **never guessed.** Raw value kept, amber warning "unit unclear", the Fahrenheit conversion attached as a SUGGESTION (`suggestion.value`) — shown in the UI, applied only by an explicit operator click |

Rationale: a misread number passing through a conversion can become a
plausible-but-wrong Fahrenheit value (observed: misread `38` → converted
`100.4 °F` — a dangerous error). Conversion therefore only happens on an
explicit, plausible Celsius reading; validation runs on the raw value first.

## Glucose (fasting) and HbA1c

The source dataset's glucose columns hold **mmol/L-like** (3.5–8.9) and
**mmol/mol-like** (30–50) values even though its headers say "mg/dl"
(`mlcore/constants.py::DATASET_NOTES`). Policy:

| situation | behavior |
|---|---|
| line says `mmol/L` (or no unit) and value in the dataset scale | accepted |
| line says `mg/dL` but value is in the dataset scale | **ambiguous** — amber warning, value NOT converted |
| line says `mg/dL` and value matches an mg/dL scale | red — "value does not match the system's scale — please correct" |
| line says `%` for HbA1c while the value is mmol/mol-scale | **ambiguous** — amber warning, not converted |
| value outside the plausible range regardless of unit | red; the decimal-suggestion layer may attach an amber "did you mean X?" proposal |

## Decimal suggestions

When a value fails its plausibility range but becomes plausible by inserting
a decimal point (`365 → 36.5`, `975 → 97.5`, `57 → 5.7`), the validator
attaches `suggestion.value` and an amber warning. **The raw value is kept,
`valid` stays false, and nothing is auto-applied** — the UI shows a
"Use X?" button that fills the field only when the operator clicks it.

## Cascade compute policy

One fast pass (grayscale + cubic upscale to ≥2200 px) always runs. The
CLAHE/background-normalization variant and per-field crop re-reads (digit
whitelist, psm 7) run **only** when fields are missing, low-confidence, or
failed validation. The hard-threshold pass is optional (`OCR_THRESHOLD_PASS=1`)
because it measurably destroys decimal points.
