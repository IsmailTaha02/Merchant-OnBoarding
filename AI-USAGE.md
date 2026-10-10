# AI Usage Report

## Tools used

- OpenAI Codex desktop, powered by GPT-6, was used as a coding and review assistant for this project.
- This report documents Codex use visible in the project conversation. Add any other AI tools or models used by the candidate before submission; none are recorded here.

## How AI assisted

Codex was used to:

- Compare the implementation with the supplied merchant-onboarding assessment and turn requirements into a verification checklist.
- Review and modify application, frontend, infrastructure, test, and documentation files.
- Diagnose defects from test results and user-reported behavior.
- Run the existing test suite and local syntax/compile checks, and inspect desktop and narrow-screen frontend rendering.
- Draft or revise technical documentation, including this report.

Representative prompts included:

- “Recheck the assignment requirement and see if something [is] missing.”
- “Test the project — test each required point.”
- “Improve interfaces to be more modern.”
- “I can’t press the continue button (it shows a loading mouse).”

## AI-generated versus candidate-directed work

The implementation has been developed through iterative AI-assisted work. Codex generated or substantially revised code and documentation in response to candidate goals and feedback. The candidate supplied the assignment and project direction, chose priorities, reviewed the outputs, attempted the AWS setup, reported observed UI and AWS errors, and decided which project limitations to accept for the assessment.

The current project directory has no Git repository or prior commit history. As a result, it is not possible to reliably attribute every pre-existing file or line to a particular person or AI session. This report does not claim that the candidate manually authored code that may have been AI-generated. Review the repository’s future commit history and update this section if the original source repository or additional AI-use records are recovered.

## Examples of review, correction, and AI weaknesses

- During the frontend refinement, a desktop/mobile browser inspection exposed a mobile sidebar retaining a desktop minimum height. The CSS was corrected after inspecting the rendered page.
- The Continue control was disabled on the review step and during incomplete evaluation, so it appeared to be loading. The UI was changed to keep the action clickable and show the server’s completeness response; submission remains gated by server validation and final attestation. A regression test was added.
- A document reviewer status API was added, but later review identified that the prototype still lacks a reviewer dashboard and a safe document-download route. The limitation is documented rather than presented as a complete reviewer experience.
- AWS CLI sign-in troubleshooting did not resolve the `CreateOAuth2Token` validation error. AWS deployment and hosted sign-in are therefore explicitly reported as unverified; no successful cloud deployment is claimed.

## Verification performed

- `python -m unittest discover -s tests -q`: 60 tests passed after the Continue-button regression test was added.
- `node --check frontend/app.js`: passed.
- `python -m compileall -q src tests scripts`: passed.
- Desktop and narrow-screen frontend layouts were inspected in local Chrome. This is a visual spot-check, not a full browser end-to-end test.
- SAM validation/build passed in an earlier session but could not be rerun in the latest environment because SAM CLI was unavailable on the command path.
- A deployed AWS smoke test was not possible because CLI authentication/account verification did not complete. Do not infer live AWS behavior from the local test suite.

## Remaining limitations

The system prepares an intake and human-review package; it does not perform identity verification, credit checks, sanctions screening, malware scanning, or final underwriting. Evaluation is deterministic and the AI-summary adapter is a mock. MCC suggestion confidence values are uncalibrated heuristics. The reviewer API has no reviewer UI or secure document retrieval route. AWS deployment, hosted authentication, and real S3/DynamoDB integration have not been verified.

Use synthetic data only for the assessment demo. Before submission, the candidate should confirm the factual accuracy of this report and add any AI tools/models or substantial personal code contributions not captured above.
