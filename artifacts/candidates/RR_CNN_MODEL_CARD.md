# SomniSignal Compact RR-CNN Model Card

## Status

Deployed for adult research analysis. Clinical release gate passed: **false**.

## Intended use

Adult ECG-derived research screening only. This model is not diagnostic and
cannot replace polysomnography or technically adequate home sleep-apnea testing.

## Data and limitations

- PhysioNet Apnea-ECG Database v1.0.0, DOI:10.13026/C23W2R.
- 34 records after excluding duplicate c06.
- Small, old, demographically limited data with important age/sex imbalance.
- Five-minute RR sequences are an ECG surrogate for respiratory disturbance.
- Validation on an independent external apnea dataset has not been completed.

## Validation

Three repeated five-fold patient-grouped validation using WFDB GQRS produced:

- Sensitivity: 0.850
- Specificity: 0.889
- Balanced accuracy: 0.869 (bootstrap 95% CI 0.717–0.975)
- Minute Brier score: 0.124 (bootstrap 95% CI 0.094–0.152)
- Borderline records inconclusive: 1 of 5 (required: at least 3 of 5)

The model passed the primary A/C sensitivity, specificity, and balanced-accuracy
thresholds and is deployed for the research demonstration. It remains blocked
from clinical release because borderline behavior, independent external
validation, privacy, security, and regulatory gates are incomplete.
