# GWEB assessment readiness

This checklist maps the supplied assessment PDF to the current project and local verification results. It distinguishes implemented prototype behavior from AWS-hosted or production behavior that was not verifiable here.

## Acceptance criteria

| Requirement | Status | Evidence and remaining work |
|---|---|---|
| End-to-end application journey | Pass locally | Handler-level test covers create/idempotent resume, business and applicant data, document upload flow, MCC classification, evaluation, attestation, and submission. Browser includes the corresponding steps and local demo. Cloud-hosted browser/API flow still requires AWS deployment. |
| Business, owner/controller, entity, address and volume data | Pass locally | Required fields are validated server-side and represented in the UI, typed data, review summary, and normalized payload. Includes masked registration suffix, owner/controller details, expected volume/ticket/count/channel split, licensing, and masked settlement details. |
| Documents and lifecycle | Pass locally with stated limits | Private S3 upload lifecycle covers `UPLOADING`, `RECEIVED`, `UPLOAD_EXPIRED`, `SUPERSEDED`, and reviewer transitions `PROCESSING`, `ACCEPTED`, `NEEDS_REVIEW`, `REJECTED`. Reviewer actions are group-gated, reasoned where needed, audited, state-checked, and idempotent. Local tests cover transitions/retries. No reviewer dashboard/download route or malware scanning is provided. |
| MCC and provider policy | Pass for assessment prototype | Search uses 924 four-digit Visa code/title entries and metadata identifies the April 2026 Visa manual. Suggestions are separately curated and may be empty; provider policy is separate and explicitly illustrative. Import tests verify validation, metadata, and preservation of keywords. Refresh against the assessment’s intended source/version before submission if it differs. |
| Evaluation, statement rates, explainable flags | Pass for deterministic prototype | Missing fields/docs, owner share gaps, volume/ticket inconsistencies, policy tags, and MCC/activity mismatches produce source-linked flags. Sanitized statement totals support fee/effective-rate calculation. AI summary is a replaceable deterministic mock; confidence values are uncalibrated heuristics. No ID, credit, sanctions, OCR, or final underwriting decision is performed. |
| Submit and normalized review payload | Pass locally | Completeness and final attestation gate submission, writes are locked after submission, and decision state is pending human review. Reviewer document transitions only become available after submission. |
| Lambda-only architecture and 45-second limit | Pass by source contract; AWS unverified | SAM template declares Lambda functions with 40-second timeout; internal deadline is 35 seconds, SDK calls are bounded, retries are disabled, and slow dependency behavior is tested. Infrastructure contract tests verify Lambda-only compute and required AWS resources. Deployed latency and AWS runtime behavior have not been measured. |
| Security and privacy | Strong prototype controls; production incomplete | Cognito JWT/MFA, per-application ownership, reviewer group, scoped IAM, private/versioned/encrypted S3, TLS-only bucket policy, masked sensitive values, no PAN/CVV fields, file validation, minimal logs, bounded uploads/records, optimistic writes, audit subjects, throttling, and parameterized CORS are present. Still needed before real data: deployed auth check, malware quarantine/scanning, reviewer file access design, retention/legal-hold approval, WAF/per-user abuse controls, operational alarms, and security review. |
| Types, modularity, tests, documentation | Pass locally for assessment scope | TypedDict models, repository/provider boundaries, OpenAPI, architecture/security/readiness notes, walkthrough, cleanup instructions, and 59 standard-library tests are present. Formal schema validation is not comprehensive. |

## Local verification performed

- `python -m unittest discover -s tests -q`: **60 tests passed**. Coverage includes domain validation, review transitions and idempotency, applicant ownership, deadline handling, MCC catalog/import behavior, policy separation, rate analysis, cleanup, frontend/static security contracts, infrastructure contracts, the review Continue-button regression, and a handler-level end-to-end workflow.
- `node --check frontend/app.js`: passed.
- `python -m compileall -q src tests scripts`: passed.
- Earlier session: `sam validate --lint --region eu-west-2` and `sam build` passed. SAM CLI is not available in the current environment, so those checks were not repeated.
- No AWS deployment, hosted sign-in, live S3/DynamoDB smoke test, or deployed timeout measurement was possible in this session. The AWS account verification issue previously reported remains an external prerequisite.
- OpenAI Codex (GPT-6) was used during development; see [AI-USAGE.md](../AI-USAGE.md) for the usage report and attribution limitations.

## Remaining submission work

1. Once AWS account verification is complete, run SAM validate/build, deploy a disposable stack, and smoke-test authenticated create/resume, every form/update route, presigned upload/complete, MCC search/classification, evaluation, submission lock, reviewer transitions, and cleanup behavior. Capture evidence and delete the test stack afterward.
2. Decide whether assessment specifically expects a reviewer-facing dashboard or only a review-ready submission package. The API exposes reviewer transitions but this project has no reviewer UI or document-download route.
3. Confirm the expected MCC source/version against the PDF; current catalog is Visa April 2026. Keep the source attribution and importer metadata aligned.
4. Keep policy examples labeled fictional and confidence values described as uncalibrated.
5. Use only synthetic data and describe the system as intake/review preparation, not identity verification or automated approval.

See [README.md](../README.md), [architecture.md](architecture.md), and [security-note.md](security-note.md) for implementation and operating details.
