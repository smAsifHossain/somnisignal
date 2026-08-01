# SomniSignal test records

These files are public, de-identified research records from the
[PhysioNet Apnea-ECG Database](https://physionet.org/content/apnea-ecg/1.0.0/).
They are packaged as zipped WFDB records and can be uploaded directly in the
SomniSignal interface. The sampling rate is read from the WFDB header, so the
sampling-rate field is not used for these ZIP files.

| File | PhysioNet group | Useful test |
| --- | --- | --- |
| `physionet-a01-wfdb.zip` | Apnea class | Existing higher-burden example |
| `physionet-a02-wfdb.zip` | Apnea class | Second higher-burden example |
| `physionet-a03-wfdb.zip` | Apnea class | Higher-risk test example |
| `physionet-a04-wfdb.zip` | Apnea class | Higher-risk test example |
| `physionet-a05-wfdb.zip` | Apnea class | Higher-risk test example |
| `physionet-b01-wfdb.zip` | Borderline class | Ambiguous/borderline behavior |
| `physionet-c01-wfdb.zip` | Control class | Low-burden control behavior |
| `physionet-c02-wfdb.zip` | Control class | Second low-burden control example |
| `physionet-c03-wfdb.zip` | Control class | Lower-risk test example |
| `physionet-c04-wfdb.zip` | Control class | Lower-risk test example |
| `physionet-c05-wfdb.zip` | Control class | Lower-risk test example |
| `physionet-a01.csv.gz` | Apnea class | Tests the one-column CSV.GZ path at 100 Hz |
| `synthetic-ecg-6h-100hz.csv.gz` | Synthetic | Tests CSV.GZ upload and quality checks at 100 Hz |

The A/B/C group is the dataset category, not a guaranteed SomniSignal result.
Differences between the known group and the model output are useful evidence of
false positives, false negatives, or an inconclusive screen. SomniSignal is a
research prototype and must not be used to diagnose or rule out sleep apnea.
