# FD Process Stability Rule (Non-Negotiable)

Goal: Prevent regressions where a previously-working workflow/process is accidentally broken.

Rule:
1) If a workflow has been observed working in Actions at least once, it is considered "working process".
2) A working process must not be modified unless:
   - the change is introduced by a dedicated WI (Tech Debt or Feature),
   - the change includes updated verification steps,
   - and CI includes an automated check that would have caught the prior breakage mode.

For this repo:
- .github/workflows/agent_run.yml is a working process.
- Any change to agent_run.yml must keep:
  - ASCII-only
  - no tabs
  - no regex artifacts (e.g., \1)
  - no heredocs inside YAML
  - workflow_dispatch inputs include type: string
- CI runs tools/validate_workflows.py and fails fast on violations.

If you need to change behavior, prefer:
- adding new steps rather than restructuring existing ones
- adding new scripts under tools/ with deterministic behavior
