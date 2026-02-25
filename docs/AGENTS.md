# FD Agents (Executable, cost-free)

FD provides repo-native agents that run in GitHub Actions without paid LLM API calls.

Core rules:
- Agents run deterministic, code-defined actions only.
- Each agent produces its own artifact bundle as a ZIP under evidence/WI-###/<role>/.
- Each agent opens a GitHub Issue for the next agent in the pipeline.
- No PR is created until the final agent marks the pipeline complete.
- Changes are accumulated on a pipeline branch and only proposed as a PR at the end.

## Triggering agents (GitHub Issues)

Create an Issue and add label: agent-run

Issue body must be JSON:

{
  "pipeline_id": "P-20260225-001",
  "work_item": "WI-002",
  "role": "tech_lead",
  "next_role": "fe",
  "next_task": "Implement docs UI navigation enhancements",
  "actions": [
    {"type": "write_file", "path": "docs/NOTE.md", "content": "example"}
  ]
}

Notes:
- actions are executed by tools/agent_pipeline.py
- role config controls allowed action types

## Branch and PR behavior

- All changes are committed to: pipeline/<pipeline_id>
- No PR is opened until the pipeline is complete (no next_role).
- When next_role is empty, the workflow opens a PR from pipeline/<pipeline_id> to main.

## Local run

python tools/agent_pipeline.py --input tools/example_issue_input.json --out evidence/WI-002/tech_lead/

## Repository size policy

- ZIP artifacts are uploaded to Actions artifacts with short retention and are not committed to git.
- The workflow deletes ARTIFACTS.zip before committing to the pipeline branch.
- evidence folders store small, textual summaries only.
