# SomniSignal compact RR-CNN model card

## Current status

SomniSignal deploys `somnisignal-rr-cnn-1.0.0` for adult research analysis. It is
not a diagnostic or clinical system because independent external validation and
the privacy, security, clinical, and regulatory gates are incomplete.

## Intended use

Adult-only research analysis of a documented 6-12 hour single-lead ECG. The
output is a sleep-apnea risk prediction based on ECG-derived cardiac patterns. It
is not a diagnosis, cannot rule apnea in or out, and cannot replace
polysomnography or a technically adequate home sleep-apnea test.

## Model and input

- Compact one-dimensional CNN exported to ONNX and executed on CPU.
- WFDB GQRS detection followed by physiologic RR validation.
- Five-minute RR sequences interpolated at 4 Hz, advanced once per minute.
- Platt calibration applied to the CNN logits.
- Nightly aggregation uses the validated probability threshold and burden rules.

## Training data

PhysioNet Apnea-ECG Database v1.0.0, DOI `10.13026/C23W2R`. Training uses the 35
learning records with minute annotations and removes `c06`, a duplicate of `c05`,
leaving 34 recording-level patient groups.

## July 2026 grouped validation

Three repeated five-fold stratified patient-grouped validation runs using WFDB
GQRS-derived intervals produced:

- A/C patient sensitivity: 0.850.
- A/C patient specificity: 0.889.
- A/C patient balanced accuracy: 0.869 (bootstrap 95% CI 0.717-0.975).
- Minute Brier score after calibration: 0.124 (bootstrap 95% CI 0.094-0.152).
- Mean fold window balanced accuracy: 0.817.
- Probability threshold: 0.3305.
- Borderline records returning inconclusive: 1 of 5.
- ONNX artifact SHA-256: `b3d959f9d436de6bd0da9d98ab30512a4d1a1c227f04e7ca9a2f95ac11b32ef3`.

The CNN replaces the logistic-regression research baseline because its A/C
patient-level balanced accuracy is materially higher. The result does not count
as independent external validation because all 34 records contribute to the
final fitted artifact.

## Material limitations

- The cohort is small, old, and demographically limited, with known age and sex
  imbalance.
- ECG-derived RR variation is only a surrogate for respiratory disturbance and
  is affected by rhythm disorders, medication, autonomic state, recording
  hardware, and noise.
- A lower-risk result cannot rule out obstructive or central sleep apnea.
- Pediatric use, diagnosis, treatment selection, and monitoring are out of scope.
- Consumer wearable files may not match the documented single-lead ECG input.
- Borderline performance remains insufficient for clinical deployment.

See [`RELEASE_GATES.md`](RELEASE_GATES.md) for the remaining public-release requirements.
