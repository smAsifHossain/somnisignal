# SomniSignal test records

These files are public, de-identified research records from the
[PhysioNet Apnea-ECG Database](https://physionet.org/content/apnea-ecg/1.0.0/).
Use the file-name links below to download a record, then upload it through the
[SomniSignal application](https://smasifhossain.github.io/somnisignal/).
The binaries are stored as versioned assets in the
[SomniSignal sample-data release](https://github.com/smAsifHossain/somnisignal/releases/tag/sample-data-v1),
keeping large test files out of the source-code history.

For the simplest first test, download `physionet-a01-wfdb.zip`. Keep the archive
zipped and leave the ECG channel set to `auto`. A zipped WFDB record contains its
sampling rate in the header, so the sampling-rate field is ignored. For either
CSV.GZ example, enter `100` Hz before analysis.

| Download | Dataset group | Test profile |
| --- | --- | --- |
| [physionet-a01-wfdb.zip](https://github.com/smAsifHossain/somnisignal/releases/download/sample-data-v1/physionet-a01-wfdb.zip) | Apnea class | Higher-burden · WFDB ZIP |
| [physionet-a02-wfdb.zip](https://github.com/smAsifHossain/somnisignal/releases/download/sample-data-v1/physionet-a02-wfdb.zip) | Apnea class | Higher-burden · WFDB ZIP |
| [physionet-a03-wfdb.zip](https://github.com/smAsifHossain/somnisignal/releases/download/sample-data-v1/physionet-a03-wfdb.zip) | Apnea class | Higher-burden · WFDB ZIP |
| [physionet-a04-wfdb.zip](https://github.com/smAsifHossain/somnisignal/releases/download/sample-data-v1/physionet-a04-wfdb.zip) | Apnea class | Higher-burden · WFDB ZIP |
| [physionet-a05-wfdb.zip](https://github.com/smAsifHossain/somnisignal/releases/download/sample-data-v1/physionet-a05-wfdb.zip) | Apnea class | Higher-burden · WFDB ZIP |
| [physionet-b01-wfdb.zip](https://github.com/smAsifHossain/somnisignal/releases/download/sample-data-v1/physionet-b01-wfdb.zip) | Borderline class | Borderline · WFDB ZIP |
| [physionet-c01-wfdb.zip](https://github.com/smAsifHossain/somnisignal/releases/download/sample-data-v1/physionet-c01-wfdb.zip) | Control class | Lower-burden · WFDB ZIP |
| [physionet-c02-wfdb.zip](https://github.com/smAsifHossain/somnisignal/releases/download/sample-data-v1/physionet-c02-wfdb.zip) | Control class | Lower-burden · WFDB ZIP |
| [physionet-c03-wfdb.zip](https://github.com/smAsifHossain/somnisignal/releases/download/sample-data-v1/physionet-c03-wfdb.zip) | Control class | Lower-burden · WFDB ZIP |
| [physionet-c04-wfdb.zip](https://github.com/smAsifHossain/somnisignal/releases/download/sample-data-v1/physionet-c04-wfdb.zip) | Control class | Lower-burden · WFDB ZIP |
| [physionet-c05-wfdb.zip](https://github.com/smAsifHossain/somnisignal/releases/download/sample-data-v1/physionet-c05-wfdb.zip) | Control class | Lower-burden · WFDB ZIP |
| [physionet-a01.csv.gz](https://github.com/smAsifHossain/somnisignal/releases/download/sample-data-v1/physionet-a01.csv.gz) | Apnea class | Higher-burden · CSV.GZ |
| [synthetic-ecg-6h-100hz.csv.gz](https://github.com/smAsifHossain/somnisignal/releases/download/sample-data-v1/synthetic-ecg-6h-100hz.csv.gz) | Synthetic | Synthetic · CSV.GZ |

The A/B/C group is the dataset category, not a guaranteed SomniSignal result.
Differences between the known group and the model output are useful evidence of
false positives, false negatives, or an inconclusive screen. SomniSignal is a
research prototype and must not be used to diagnose or rule out sleep apnea.
