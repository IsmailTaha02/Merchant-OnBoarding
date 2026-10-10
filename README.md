# GWEB Merchant Onboarding

A serverless merchant intake and underwriting-support prototype. A merchant can create and resume an application, enter business and control-person details, attach documents, request an MCC suggestion, review explainable checks, and submit a normalized review package. The system never approves merchants or performs identity, credit, or sanctions checks.

## Run the demo locally

The full 924-code Visa MCC directory (April 2026 edition) is searchable from the category step; deterministic activity suggestions use a smaller curated keyword set and may return no result. The browser demo runs without AWS credentials and stores clearly labelled sample data in that browser's local storage. Do not enter real personal, identity, banking, or merchant data in demo mode.

1. Open `frontend/index.html` in a modern browser, or serve the `frontend` directory with any static file server.
2. Fill the first section and select **Continue** to create the application. Work through each section and submit using fictional sample details.
3. **Reset demo** removes the local demo data.

To point the browser at a deployed API, edit `frontend/config.js` and set `apiBaseUrl` and `demoMode: false`. See **Authentication and production readiness** below before exposing the API.

## Deploy to AWS

Requirements: AWS SAM CLI, Docker (for local Lambda invocation), Python 3.12, and an AWS account/region configured for deployments.

```powershell
cd outputs/merchant-onboarding
sam build
sam deploy --guided --parameter-overrides FrontendOrigin=http://localhost:8000
```

SAM provisions API Gateway HTTP API, a Cognito user pool and hosted sign-in domain, the stateless application Lambda, an hourly retention Lambda, a private versioned S3 document bucket, a DynamoDB single table with point-in-time recovery, and CloudWatch logs. The retention Lambda is disabled by default (`RetentionPolicy={}`). Only configure it with status-to-days values after a compliance-approved policy is available; for example, `RetentionPolicy='{"DRAFT":90,"SUBMITTED":365}'` is illustrative syntax only, not a recommended schedule. API routes require Cognito JWTs. Each application is tied to the authenticated Cognito subject, and a different signed-in user receives a not-found response when trying to access it.

For a local assessment run, use `http://localhost:8000` as `FrontendOrigin`. After deployment, configure the browser app from the CloudFormation outputs with `./scripts/configure-frontend.ps1`, then serve the frontend in another PowerShell window with `python -m http.server 8000 --directory frontend`. Cognito permits localhost HTTP callbacks for testing. Open `http://localhost:8000`; users can sign in or create an account through Cognito, verify their email, and enroll a TOTP authenticator because MFA is required. For a hosted site, redeploy with its exact HTTPS origin as `FrontendOrigin` and run `./scripts/configure-frontend.ps1 -FrontendOrigin https://your-site.example`. Do not use localhost for public hosting. Backend application compute remains Lambda-only.

This remains an assessment prototype, not a production payment-provider onboarding service. The stack requires TOTP MFA, applies API throttling, logs only request IDs/route templates/status/latency, and denies non-TLS S3 access. It does not perform identity verification, credit checks, sanctions screening, malware scanning, or final underwriting. Before real data or public use, configure a custom domain/WAF and per-user quotas as appropriate, review encryption key and retention policy with security/legal, and test operational alarms and recovery. The stack does not expose a public document bucket.

## API

All routes are under `/v1` and use JSON unless the response is a presigned URL.

| Method | Route | Purpose |
|---|---|---|
| POST | `/v1/applications` | Create an application |
| GET | `/v1/applications/{id}` | Load application and related records |
| PATCH | `/v1/applications/{id}/applicant` | Save control-person details |
| PATCH | `/v1/applications/{id}/business` | Save business details |
| POST | `/v1/applications/{id}/documents/presign` | Create restricted S3 upload URL |
| POST | `/v1/applications/{id}/documents/{documentId}/complete` | Verify uploaded object and record metadata |
| POST | `/v1/applications/{id}/documents/{documentId}/review` | Reviewer-only document status transition after submission |
| POST | `/v1/applications/{id}/statement/parse` | Parse sanitized statement totals without retaining raw text |
| GET | `/v1/mcc?query=clothing` | Search the complete Visa MCC catalog |
| POST | `/v1/applications/{id}/classify` | Suggest MCC candidates and policy tags |
| POST | `/v1/applications/{id}/evaluate` | Run deterministic completeness and consistency checks |
| GET | `/v1/applications/{id}/evaluation` | Read latest evaluation |
| POST | `/v1/applications/{id}/submit` | Validate and lock a version for human review |

The HTTP API uses API Gateway proxy events. Example:

```json
POST /v1/applications
{"idempotencyKey":"demo-001"}
```

Every Lambda invocation applies an internal deadline below the 45-second application limit. Calls to S3 and DynamoDB are bounded by SDK timeouts; no third-party AI dependency is required. Evaluation uses deterministic rules and a clearly labelled mock summary adapter. Uploaded PDFs are not OCR-processed. An optional parser accepts only a narrow, documented text format for sanitized statement totals; it calculates itemized fees and effective rate and discards the raw text. Parsed values are unverified and must be checked against the original statement.

## Data, safety, and design

- S3 holds document bytes; DynamoDB holds the application record (including applicant, owners, and business data), document metadata, classifications, evaluations, and submission records (`PK=APP#{id}`, `SK=META|DOC#{id}|EVAL#{id}|SUBMISSION#{version}`). Idempotency records use a separate `IDEMPOTENCY#{key}` partition.
- Direct uploads use short-lived presigned POSTs. The object key is generated by the service, MIME type and maximum size are constrained, bucket public access is blocked, and objects are encrypted and versioned. Completion pins the uploaded S3 version and stores a SHA-256 digest after validating the file signature.
- Allowed file formats are PDF, JPEG, and PNG. Completion verifies object existence, content length, content type, checksum, and file signature. Presigned links expire after five minutes; replacements mark the previous record as superseded. Optional additional underwriting evidence records the applicant-provided reason. The API supports audited reviewer transitions after submission (`RECEIVED → PROCESSING → ACCEPTED`, `NEEDS_REVIEW`, or `REJECTED`); `NEEDS_REVIEW` and `REJECTED` require a reason. Reviewer access is limited to the Cognito `underwriting-reviewer` group, which must be assigned to reviewer accounts by an administrator. A reviewer dashboard/download workflow and malware scanning are not included.
- Raw government ID/tax/bank numbers are not requested by this prototype. Only masked/last-four metadata is accepted. Do not put PII in logs.
- The form supports one primary applicant plus up to 20 additional beneficial owners/controllers, each with a structured residential address and masked ID metadata. Business registered addresses are captured as separate address components. Optional profile details capture regions served, fulfillment model, recurring-payment behavior, and customer type; the mock summary reflects only applicant-entered values and marks itself unverified. Evaluation requires address, expected annual volume, average/largest ticket, monthly count, and card-present/card-not-present/e-commerce estimates. The applicant must also declare whether licensing applies and provide settlement account holder, bank name, and last four digits; bank evidence is a required upload. Registration ID and business-license numbers are stored as four-character masked suffixes. When a license is required, type, issuer, expiry, and a license document are required. Owner/Partner shares are required, and missing or incomplete ownership totals generate explainable review flags; thresholds and ownership rules must be confirmed for the actual provider and jurisdiction.
- Cognito login and per-application ownership are now implemented in the SAM deployment. Identity verification, sanctions screening, OCR, malware scanning, and final underwriting remain outside this assessment prototype.
- Writes use conditional creation/version checks where applicable. Retry-safe create supports an idempotency key.
- Each warning includes a reason and the exact source field/document reference. These checks identify missing or internally inconsistent information; they cannot prove identity or determine whether entered facts are true. MCC taxonomy is separate from configurable policy tags; policy tags are not a universal risk verdict.
- `src/mcc_catalog.json` contains 924 four-digit MCC/title entries extracted from Section 2 of Visa’s April 2026 Merchant Data Standards Manual; provenance is recorded in `src/mcc_catalog_metadata.json`. The list is Visa-specific; confirm provider-specific eligibility and refresh the cited edition before operational use. Search supports the complete catalog; activity suggestions use curated keywords and can return no suggestion.
- Submission is blocked when required information/documents are missing and emits a versioned normalized internal review payload. A successful submission means “ready for human review,” not “approved.”
- `template.yaml` grants the function table access and narrowly scoped S3 object access. The demo template is suitable for evaluation, not a substitute for a production threat model.

## Verify

Run the included standard-library test suite:

```powershell
python -m unittest discover -s tests -v
```

`tests/test_deadline.py` verifies that a simulated hanging dependency times out before the hard 45-second boundary. Test fixtures contain no real applicant information.

## Assessment references

- [Visa Merchant Data Standards Manual (April 2026)](https://usa.visa.com/dam/VCOM/download/merchants/visa-merchant-data-standards-manual.pdf)
- [AWS SAM](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/what-is-sam-overview.html)
- [Amazon S3 presigned uploads](https://docs.aws.amazon.com/AmazonS3/latest/userguide/PresignedUrlUploadObject.html)

## Remove a deployed test stack

Before deleting a deployed stack, empty its versioned document bucket in the Amazon S3 console, including all object versions and delete markers. Deleting only current objects is not enough for a versioned bucket. Confirm that the test data is no longer needed; stack deletion removes the application's DynamoDB table and Cognito pool.

```powershell
sam delete --stack-name gweb-merchant-onboarding --region eu-west-2
```

Use the stack name and region selected during deployment if they differ. The local demo can be cleared with **Reset demo** in the browser.

## Architecture details

See [docs/architecture.md](docs/architecture.md) for the Mermaid request-flow diagram, storage keys, deadlines, and known security gaps. See [docs/assessment-readiness.md](docs/assessment-readiness.md) for criterion status and [docs/demo-walkthrough.md](docs/demo-walkthrough.md) for a synthetic demo.

For assessment transparency, see [AI-USAGE.md](AI-USAGE.md) for the AI tools used, representative assistance, review and verification steps, and known limitations. Confirm its accuracy and add any other tools/models used before submission.

The scheduled cleanup worker removes all versions and delete markers under an expired application's S3 prefix before deleting its DynamoDB partition. It handles one application per invocation and retries partial work on a later schedule. It does not support legal holds or write a separate deletion audit record; add those controls before operational use.

To remove a disposable assessment stack after testing, run `sam delete --stack-name <stack-name>` from this project directory and follow the prompts. This removes the stack resources; review and empty any retained S3 object versions first if CloudFormation reports that the bucket is not empty. CloudWatch log groups use a configurable retention period (`LogRetentionDays`, default 30 days).
