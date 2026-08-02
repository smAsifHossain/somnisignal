# Release gates

Clinical deployment remains outside the current scope until every checkbox is
completed and evidence is retained outside the application repository.

## Model and performance

- [x] Training used 34 unique records after excluding duplicate `c06`.
- [x] Automated fold-isolation assertion passed.
- [x] A/C patient sensitivity is at least 0.80.
- [x] A/C patient specificity is at least 0.80.
- [x] Patient balanced accuracy is at least 0.80.
- [x] Brier score and patient-group bootstrap 95% confidence intervals are reported.
- [ ] Borderline B records normally return `inconclusive`.
- [ ] Independent reviewer reproduced the artifact SHA-256 and metrics.

## Privacy, legal, and clinical claims

- [ ] FDA digital-health/device-software policy assessment is complete.
- [ ] FTC Health Breach Notification Rule and HIPAA applicability are reviewed.
- [ ] Public privacy notice is approved and published.
- [ ] Breach-response and user-notification procedure is approved.
- [ ] Adult-only consent and non-diagnostic claims are reviewed.
- [ ] Clinical messaging aligns with AASM guidance on PSG/HSAT.

## Security and operations

- [ ] Independent security review and remediation are complete.
- [ ] Tunnel accepts only authenticated HTTPS traffic from the hosted proxy.
- [ ] Worker secrets are configured outside source control and rotated/tested.
- [ ] Turnstile, exact three-per-hour rate limit, CORS, and header stripping pass E2E tests.
- [ ] Online, offline, busy, restart, cancellation, expiry, and raw-file deletion pass E2E tests.
- [ ] Exact ten-hour laptop benchmark completes in under 90 seconds with peak container memory below 700 MB. (Closest public record: 9.62 hours, 39.99 seconds, 463.5 MiB; exact-duration check remains open.)
- [ ] Logs are verified to contain no filenames, ECG values, tokens, IPs, bodies, or prediction results.

Only after all items pass may both `PUBLIC_UPLOADS_ENABLED` and
`REGULATORY_REVIEW_COMPLETE` be set to `true`.
