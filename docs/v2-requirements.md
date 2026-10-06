# V2 approved requirements

Status: design and implementation pending; this document does not claim deployment.

- Professional financial research UI; retain old releases and reports.
- Require password login before loading protected data; blur an empty dashboard shell only.
- Password maintained in Cloudflare APP_PASSWORD secret; never embed secrets in frontend assets.
- All three return-order comparisons independently optional, including disabling all three.
- Expose eligibility conditions and numeric thresholds; distinguish eligibility, scoring, and entry signals.
- Validate configuration server-side; save immutable configuration with each job, report and email.
- Missing data must remain missing, not zero. All funds considered unheld.
- Preserve five existing entry signals and drawdown/provenance fields.
- Verify authentication, configuration propagation, UI interactions, full scan and email separately.
- ImageGen2 artwork currently blocked by missing local OPENAI_API_KEY; no generated artwork claimed.
