# Superseded feature-model card

The class-weighted logistic-regression artifact in this directory is retained
only as a reproducibility baseline. It is no longer loaded by the SomniSignal API.

The deployed research-demonstration model is the compact RR-CNN documented in
`artifacts/candidates/RR_CNN_MODEL_CARD.md` and `MODEL_CARD.md` at the repository
root.

The baseline's grouped-validation performance was sensitivity 0.950,
specificity 0.222, and balanced accuracy 0.586. It was superseded because its
false-positive burden on control records was unacceptable.
