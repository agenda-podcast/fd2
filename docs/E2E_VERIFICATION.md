# E2E Verification (FD)

Canonical: docs/E2E_VERIFICATION.md

## Environments and entry criteria
Local:
- Entry: clean repo clone
- Tools: browser + python3
- Notes: no build required for docs UI

Dev/Staging/Prod:
- Define when created.

## Deterministic test data
- Not applicable for docs-only baseline.

## Scenarios

### E2E-001: Docs UI loads offline
Related WIs: WI-001
Preconditions:
- Repo cloned.
Steps:
1) Open docs/index.html in a browser.
Expected results:
- Left navigation renders.
- Default page content renders.
Evidence required:
- Screenshot saved under evidence/WI-001/

### E2E-002: CI enforces ASCII-only and line limits
Related WIs: WI-001
Preconditions:
- GitHub Actions enabled.
Steps:
1) Introduce a prohibited non-ASCII character into a checked file and run CI.
2) Increase a checked file beyond 500 lines and run CI.
Expected results:
- CI fails with deterministic messages.
Evidence required:
- CI run link recorded in the WI.

## Regression matrix
- If docs UI changes: rerun E2E-001.
- If policy tools change: rerun E2E-002.
