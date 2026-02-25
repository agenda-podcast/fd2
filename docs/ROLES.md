# Roles

## Owner (Founder / Business Owner)
Produces:
- Milestone Intent Brief
- Milestone Approval
- Milestone Acceptance Memo

Loop closure:
- Milestone success signal is clear, constraints non-contradictory, scope boundary approved.

## Product Manager (PM)
Produces:
- WI decomposition
- WI prioritization and dependencies
- Acceptance criteria quality control

Loop closure:
- Open questions resolved, ACs testable, scope boundary explicit.

## UX
Produces:
- UI specs for GitHub Pages docs UI
- Information architecture

Loop closure:
- PM accepts spec, no unanswered UX questions.

## Tech Lead (Architecture / Delivery Lead)
Produces:
- Technical Approach Note
- Implementation plan
- Interfaces and NFRs
- Release readiness criteria

Loop closure:
- PM signs off feasibility and scope fit.
- DevOps confirms deploy/monitor requirements implementable.

## Frontend Engineer (FE)
Produces:
- UI components and client-side logic (GitHub Pages UI or pipeline app UI)
Loop closure:
- Reviewer checklist passes, CI green, PR merged.

## Backend Engineer (BE)
Produces:
- Services/APIs/scripts (orchestrator tools as assigned)
Loop closure:
- Reviewer checklist passes, CI green, PR merged.

## DevOps / Platform Engineer
Produces:
- CI and release workflows
- Observability and rollback mechanics
Loop closure:
- Deployment repeatable, rollback verified once, monitoring detects key failure modes.

## Code Reviewer
Produces:
- PR decision and checklist annotations
Loop closure:
- Change requests addressed, CI green, PR merged.

## QA Lead
Produces:
- Verification record and regression checks
Loop closure:
- Fix deployed to target env, cannot reproduce original issue, regression passes.

## Release Manager (optional)
Produces:
- Release execution record
Loop closure:
- Post-release monitoring completed, rollback not required.
