# Security and privacy note

## Prototype controls in place

- API Gateway provides the HTTPS entry point. Lambda uses bounded DynamoDB/S3 SDK calls and has a 40-second function timeout with a 35-second internal target.
- Cognito requires software-token MFA (TOTP). API Gateway applies a default 25 requests/second and 50-request burst limit; access logs include request ID, route template, status, and latency only.
- S3 rejects all non-TLS requests through a bucket policy. API responses include no-sniff, no-framing, no-referrer, restrictive content-security, permissions, HSTS, and no-store headers. The static frontend has a restrictive content-security policy and no-referrer policy.
- The browser escapes applicant-provided owner names before inserting them into the document checklist. A regression test protects this rendering path.
- Each application is limited to 50 document records and 40 evaluation snapshots to bound DynamoDB queries and reduce storage abuse.
- Lambda IAM is limited to the application's DynamoDB table and S3 reads/writes under `applications/*`. S3 blocks public access, enables versioning, and encrypts objects at rest. Uploads use a five-minute presigned POST with content-length, MIME, SHA-256, and key constraints.
- Upload metadata is validated at the API boundary. The service compares extension to MIME type, checks the stored size/type/checksum, and checks file signatures before recording `RECEIVED`.
- Raw document/request bodies are not logged. IDs and bank account data are limited to masked/last-four values. The prototype does not accept payment-card PAN/CVV.
- Application edits use optimistic version checks. Application and document status changes retain request ID, source label, timestamp, and authenticated Cognito subject (`actorSub`). Reviewer document transitions are restricted to the `underwriting-reviewer` Cognito group. Authentication identifies the account only; it does not verify the human’s identity. Request count, duration, and failure metrics use CloudWatch Embedded Metric Format with method/status dimensions only; no application IDs or request content enter metrics.
- Provider/risk and statement analysis are mockable modules. Statement parser accepts a strict, size-limited sanitized-text format and stores normalized amounts only.

## Threats and controls still required

- **Application access:** API Gateway requires Cognito JWT authentication, and every application read/write/upload checks the owning Cognito subject. Continue to use synthetic data for assessment; the prototype still needs security review before real PII or public production use.
- **Presigned upload leakage:** URLs are bearer credentials. Keep their lifetime short, never log them, restrict the allowed frontend CORS origin, validate ownership, and quarantine/scan uploaded objects before reviewers trust them.
- **Malicious or mismatched files:** the current signature check samples only the first bytes. Production must scan for malware, inspect full file structure, limit decompression attacks, and use a quarantine-to-accepted workflow.
- **Abuse and cost spikes:** default API throttling and a per-application document-record cap are configured. Production still needs WAF/bot controls, per-account quotas, alarms, and a budget monitor; API Gateway limits are not a replacement for per-user abuse controls.
- **Key management:** the prototype uses S3-managed encryption and DynamoDB encryption. Production should select customer-managed KMS keys, rotation, key access audits, backup recovery, and separation of duties.
- **Cross-site requests:** API Gateway and S3 CORS are parameterized to the exact HTTPS frontend origin; the deployment default is a nonfunctional placeholder, so set `FrontendOrigin` to the hosted frontend origin.
- **Retention and deletion:** an hourly scheduled Lambda is included, but its default empty `RetentionPolicy` disables deletion. Configure status-specific day counts only after compliance approval. It deletes S3 versions and delete markers before the DynamoDB partition and bounds each invocation to one application. Legal holds, a separate deletion audit record, and account/jurisdiction policy remain to be added; DynamoDB TTL alone is insufficient because it does not delete S3 objects or related partition rows.
- **Authentication and application ownership:** The browser uses Cognito hosted sign-in with OAuth authorization code + PKCE; access tokens are kept in session storage and sent as bearer tokens. The API records the authenticated Cognito `sub` as the application owner and returns not-found for access by another subject. Members of `underwriting-reviewer` may read applications and update document review states after submission. Reviewer accounts require explicit administrator group assignment. This is account authentication, not identity proofing.

## Deployment hygiene

Use environment/parameter configuration for resource names and secrets. No provider API credentials belong in source code; store them in Secrets Manager or SSM Parameter Store if a real provider is added. For assessment testing, use synthetic applicants and clearly fictional documents only.


## Document workflow controls

Upload policies are valid for five minutes. Late completion is rejected and recorded as `UPLOAD_EXPIRED`; successful replacement transitions earlier same-type documents for the same person to `SUPERSEDED`. These statuses prevent expired or replaced records from satisfying completeness checks. The API supports a group-gated reviewer lifecycle after submission, including reasoned `NEEDS_REVIEW` and `REJECTED` outcomes. No reviewer dashboard, safe document-download endpoint, or malware scanning is included; a human reviewer still needs an authorized means to inspect the file.
