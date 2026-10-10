# Demo walkthrough

This is a synthetic-data walkthrough. Do not use real identity, bank, or merchant information in the local demo.

1. Open `frontend/index.html` in a modern browser and fill the first section and choose **Continue** to create the application. The browser stores the demo application locally; **Reset demo** clears it.
2. Enter a fictional merchant such as **Northstar Coffee Ltd**, select **Limited company**, choose **United Kingdom**, enter a sample registered address, describe it as a neighbourhood coffee shop, and use an expected annual card volume of `120000`, an average ticket of `8`, a largest ticket of `40`, and `1250` monthly transactions. Enter card-present `60%`, card-not-present `40%`, and e-commerce `30%` (within the card-not-present share). Choose **No** for license required and enter fictional settlement metadata (holder, bank name, and last four digits).
3. Enter a fictional primary controller with date of birth, home address, email, phone, role, government ID type, and four sample digits. Add an additional beneficial owner/controller and provide sample-only details and ownership percentage. Save or refresh to demonstrate resume behavior.
4. At the document step, attach any harmless local PDF/JPG/PNG sample to the primary person, each additional person's government ID row, business registration, and bank evidence. Demo mode records a local file name and status only; it never transfers the file.
5. Change the license choice to **Yes**, enter its expiry date, and add a fictional business-license image/PDF to exercise the conditional evidence rule; then switch back to **No** for the regular flow.
6. Load the fictional processing-statement sample and choose **Extract totals**. The parser should report £10,000 volume, £190 fees, and 1.9%. These extracted values are unverified.
7. Search/select a suggested MCC and confirm it. On the review page, the application is checked automatically. Verify the status, source-linked warnings, rate calculation, and summary. Try removing one required owner's ID or one required business document to confirm submission is blocked.
8. Complete missing fields/documents, confirm the final attestation, and submit. The resulting state means **pending human review**, not approval. Confirm that the app locks after submission.

For backend evidence, run `python -m unittest discover -s tests -v`. This covers the HTTP handler workflow with a fake S3 adapter; it is not a deployed AWS smoke test.
