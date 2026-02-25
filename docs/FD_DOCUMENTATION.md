# FAVELLA DEVELOPMENT (FD) Documentation

Version: 1.0
Canonical location: docs/FD_DOCUMENTATION.md
Applies to: FAVELLA DEVELOPMENT only (FD-only rule)

## 0) FD-only rule (hard boundary)

This repository and its documentation must not include:
- Any description, architecture, schemas, or workflows belonging to other products.
- Any references to other repos/products as "the same thing" or as dependencies unless explicitly added as an FD dependency with an ID.

If content is not clearly FD, it does not belong here.

## 1) What FD is

FAVELLA DEVELOPMENT (FD) is a GitHub-native, role-driven engineering system that:
- Converts ideas into shippable increments using atomic work items.
- Enforces a strict 1-to-1 producer/receiver handoff model.
- Publishes a static documentation UI via GitHub Pages.
- Treats verification as a first-class deliverable (E2E Verification is always updated).

FD is an execution framework: definitions, artifacts, workflows, and checks that let contributors deliver changes predictably.

## 2) Engineering principles (non-negotiable)

### 2.1 Small Chunk deliverable criteria (Definition of Done for any deliverable)

A deliverable is acceptable only if it is:
1) Atomic
- One purpose
- One receiver
- One clear next step

2) Testable
- Objective acceptance criteria or verification evidence exists
- Pass/fail is unambiguous

3) Traceable
- References the Work Item ID and Milestone ID
- Evidence points back to the work item

4) Non-ambiguous
- The receiver can proceed with zero follow-up questions

### 2.2 1-to-1 handoff policy (strict)

- Every deliverable has exactly one producer and exactly one receiver.
- If multiple roles contribute, they contribute inputs. One owner role publishes the final artifact.
- A named receiver is required.

### 2.3 Allowed loops (only these)

Loops are allowed only in:
A) Spec refinement: PM <-> UX
B) Technical feasibility: Tech Lead <-> PM
C) Code review: Engineer <-> Code Reviewer
D) QA verification: QA Lead <-> Engineer

Every loop has a closure condition (see Section 6).

### 2.4 Always update E2E Verification

Whenever FD adds or changes:
- Functionality
- Scenarios
- Outputs
- Releases
- Schemas
- Processes

Then E2E Verification workflow/tests must be updated to include the new/changed coverage.

### 2.5 File and content constraints

- Keep every non-table logic/code file <= 500 lines.
- Do not use ellipses to omit content. No truncation.
- Use ASCII only unless a specific file is explicitly exempted in policy.
- Do not change any FD-declared sensitive or production-critical logic without explicit approval.

## 3) Repository structure (GitHub + GitHub Pages)

FD is designed to be browsable and usable directly in GitHub and via GitHub Pages.

### 3.1 Required top-level directories

- docs/
  - index.html
  - assets/
  - FD_DOCUMENTATION.md
  - WI_TEMPLATE.md
  - MILESTONE_TEMPLATE.md
  - E2E_VERIFICATION.md
  - RELEASE_RUNBOOK.md
  - GITHUB_PAGES_SETUP.md
- backlog/
  - milestones/
  - work_items/
- evidence/
  - WI-###/
- src/
- tools/
- .github/
  - workflows/

### 3.2 What each folder means

- docs: Human-facing documentation and the GitHub Pages UI entrypoint.
- backlog: Work items and milestones as versioned files.
- evidence: Attachments (screens, logs, outputs) tied to a work item.
- src: FD-owned codebase (if any).
- tools: Scripts that enforce or assist FD policies.
- .github/workflows: CI policies, doc checks, release checks.

### 3.3 GitHub Pages UI policy

- UI must be static (HTML/CSS/JS).
- UI must not require a server to render documentation.
- UI must link to canonical markdown docs and render cleanly in a browser.

Minimum UI behaviors:
- Left-nav with sections and templates
- Main panel renders markdown (client-side)
- Copy buttons for templates
- Evidence links resolve to evidence/WI-###/

## 4) Artifact system (what gets produced)

Every artifact must be:
- Versioned in Git
- Traceable to WI/Milestone
- Built for handoff

### 4.1 Artifact types (FD core)

1) Milestone Intent Brief (Owner -> PM)
2) Work Item (Producer -> Receiver)
3) Technical Approach Note (Tech Lead -> PM)
4) Implementation Branch / PR (Engineer -> Code Reviewer)
5) Evidence Pack (Engineer -> QA Lead)
6) E2E Verification Update (Owner role of change -> QA Lead)
7) Release Runbook + Execution Record (Release Manager -> Owner)

### 4.2 Artifact naming rules

- Work items: WI-###-short-title.md
- Milestones: MS-###-short-title.md
- Evidence folder: evidence/WI-###/
- PR title includes WI-###
- Commit messages include WI-### when feasible

## 5) Work Item (WI) system

A work item is the smallest independently shippable slice.

### 5.1 Work Item template (canonical)

File: docs/WI_TEMPLATE.md (use exactly this structure for every WI).

### 5.2 WI atomicity rules

A WI is invalid if:
- It has multiple receivers.
- It has "and also" scope that implies multiple independent deliverables.
- Acceptance criteria cannot be tested without interpretation.

If a WI seems big, split it into multiple WIs that can ship independently.

## 6) Roles, responsibilities, deliverables, loop closure

FD uses role separation to enforce clean handoffs and reduce ambiguity.

### 6.1 Role catalog (FD)

- Owner (Founder / Business Owner)
- Product Manager (PM)
- UX
- Tech Lead (Architecture / Delivery Lead)
- Frontend Engineer (FE)
- Backend Engineer (BE)
- DevOps / Platform Engineer
- Code Reviewer
- QA Lead
- Release Manager (optional; QA Lead can cover early)

### 6.2 Deliverables by role (FD standard)

Owner:
- Milestone Intent Brief
- Milestone Approval
- Milestone Acceptance Memo
Loop closure: milestone has clear success signal, non-contradictory constraints, approved scope boundary.

PM:
- Backlog decomposition into WIs
- WI prioritization and dependencies
- Acceptance criteria quality control
Loop closure: all open questions resolved, ACs testable, scope boundary explicit.

UX:
- UI specs for GitHub Pages UI (wireframes, flows)
- Content IA for docs UI
Loop closure: PM accepts spec, no unanswered UX questions.

Tech Lead:
- Technical Approach Note
- Implementation plan (sequenced WIs)
- Interfaces/contracts/NFRs
- Release readiness criteria
Loop closure:
- Tech Lead <-> PM feasibility: PM signs off on scope/plan fit
- Tech Lead <-> DevOps feasibility: deploy/monitor requirements implementable

Engineers (FE/BE):
- Implementation branch + PR
- Evidence pack for QA
- Telemetry/diagnostics map (if applicable)
Loop closure: reviewer checklist passes, no change requests open, build green.

DevOps / Platform Engineer:
- CI pipeline configuration
- Deploy/runbook + rollback verification
- Observability setup as required
Loop closure: deployment repeatable, rollback verified once, monitoring detects key failure modes.

Code Reviewer:
- PR decision: Approve / Request changes + checklist annotations
- Merge confirmation + summary to QA
Loop closure: all change requests addressed, CI green, PR merged.

QA Lead:
- Verification record: repro original issue fixed
- Regression checks
- Mark defect "Verified" or WI "Accepted" (as receiver)
Loop closure: fix deployed to target env, cannot reproduce original issue, regression passes.

## 7) Verification system (E2E Verification is mandatory)

File: docs/E2E_VERIFICATION.md is canonical.

E2E Verification must define:
- Test environments and entry criteria
- Test data setup (deterministic steps)
- Scenarios list with IDs (E2E-###)
- Expected outputs (exact)
- Evidence capture instructions
- Regression matrix

Scenario format:
- Scenario ID: E2E-###
- Related WIs: WI-###
- Preconditions
- Steps
- Expected results
- Evidence required

Update rule:
If a WI changes behavior, it must:
- Add or update at least one E2E scenario
- Update regression matrix if blast radius changes
- Add evidence links to evidence/WI-###/

## 8) Change control and quality gates

### 8.1 PR requirements

Every PR must include:
- Link to WI file in backlog/work_items/
- Acceptance criteria mapping
- Evidence links (screens/logs/output)
- E2E verification update if behavior changed
- Rollback note if deploy-affecting

### 8.2 CI required checks (FD baseline)

CI should fail if:
- A non-table logic/code file exceeds 500 lines
- Prohibited non-ASCII characters appear where restricted
- Required docs are missing/renamed
- WI referenced in PR title/body cannot be found (policy-dependent)
- E2E verification not updated when labeled behavior-change (policy-dependent)

## 9) Release system

File: docs/RELEASE_RUNBOOK.md is canonical.

Release readiness criteria:
- All included WIs are Accepted
- CI green on main
- E2E Verification executed for release scope
- Rollback steps are present and sanity-checked
- Known limitations are documented

Release execution record (append-only):
- Release ID / tag
- Included PRs and WIs
- Verification evidence links
- Incidents and mitigations
- Post-release monitoring summary window and outcomes

## 10) Templates (canonical references)

- docs/WI_TEMPLATE.md
- docs/MILESTONE_TEMPLATE.md
- docs/E2E_VERIFICATION.md
- docs/RELEASE_RUNBOOK.md

No template drift is allowed without a WI that updates templates and CI checks.

## 11) Known limitations

If any checks are still manual, create WIs to automate them in CI.

## 12) Maintenance of this documentation

Any change to roles, templates, CI gates, status model, E2E rules, or release rules must be introduced via a WI with acceptance criteria and evidence.

## 13) Agents (repo-native execution)

Agents may generate artifacts and propose changes, but must do so via branches and PRs. Human approval is required to merge.
