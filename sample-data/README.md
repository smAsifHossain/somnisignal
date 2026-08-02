# SomniSignal test records

These files are public, de-identified research records from the
[PhysioNet Apnea-ECG Database](https://physionet.org/content/apnea-ecg/1.0.0/).
Use the file-name links below to download a record, then upload it through the
[SomniSignal application](https://smasifhossain.github.io/somnisignal/).

For the simplest first test, download `physionet-a01-wfdb.zip`. Keep the archive
zipped and leave the ECG channel set to `auto`. A zipped WFDB record contains its
sampling rate in the header, so the sampling-rate field is ignored. For either
CSV.GZ example, enter `100` Hz before analysis.

| Download | Dataset group | Suggested use |
| --- | --- | --- |
| [physionet-a01-wfdb.zip](https://raw.githubusercontent.com/smAsifHossain/somnisignal/main/sample-data/physionet-a01-wfdb.zip) | Apnea class | Recommended first higher-burden example |
| [physionet-a02-wfdb.zip](https://raw.githubusercontent.com/smAsifHossain/somnisignal/main/sample-data/physionet-a02-wfdb.zip) | Apnea class | Second higher-burden example |
| [physionet-a03-wfdb.zip](https://raw.githubusercontent.com/smAsifHossain/somnisignal/main/sample-data/physionet-a03-wfdb.zip) | Apnea class | Higher-burden comparison |
| [physionet-a04-wfdb.zip](https://raw.githubusercontent.com/smAsifHossain/somnisignal/main/sample-data/physionet-a04-wfdb.zip) | Apnea class | Higher-burden comparison |
| [physionet-a05-wfdb.zip](https://raw.githubusercontent.com/smAsifHossain/somnisignal/main/sample-data/physionet-a05-wfdb.zip) | Apnea class | Higher-burden comparison |
| [physionet-b01-wfdb.zip](https://raw.githubusercontent.com/smAsifHossain/somnisignal/main/sample-data/physionet-b01-wfdb.zip) | Borderline class | Borderline-behavior example |
| [physionet-c01-wfdb.zip](https://raw.githubusercontent.com/smAsifHossain/somnisignal/main/sample-data/physionet-c01-wfdb.zip) | Control class | Recommended first lower-burden example |
| [physionet-c02-wfdb.zip](https://raw.githubusercontent.com/smAsifHossain/somnisignal/main/sample-data/physionet-c02-wfdb.zip) | Control class | Second lower-burden example |
| [physionet-c03-wfdb.zip](https://raw.githubusercontent.com/smAsifHossain/somnisignal/main/sample-data/physionet-c03-wfdb.zip) | Control class | Lower-burden comparison |
| [physionet-c04-wfdb.zip](https://raw.githubusercontent.com/smAsifHossain/somnisignal/main/sample-data/physionet-c04-wfdb.zip) | Control class | Lower-burden comparison |
| [physionet-c05-wfdb.zip](https://raw.githubusercontent.com/smAsifHossain/somnisignal/main/sample-data/physionet-c05-wfdb.zip) | Control class | Lower-burden comparison |
| [physionet-a01.csv.gz](https://raw.githubusercontent.com/smAsifHossain/somnisignal/main/sample-data/physionet-a01.csv.gz) | Apnea class | One-column CSV.GZ path at 100 Hz |
| [synthetic-ecg-6h-100hz.csv.gz](https://raw.githubusercontent.com/smAsifHossain/somnisignal/main/sample-data/synthetic-ecg-6h-100hz.csv.gz) | Synthetic | CSV.GZ upload and quality checks at 100 Hz |

The A/B/C group is the dataset category, not a guaranteed SomniSignal result.
Differences between the known group and the model output are useful evidence of
false positives, false negatives, or an inconclusive screen. SomniSignal is a
research prototype and must not be used to diagnose or rule out sleep apnea.
