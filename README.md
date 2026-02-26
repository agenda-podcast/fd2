# FAVELLA DEVELOPMENT (FD)

FD is a GitHub-native, role-driven engineering system that produces working software via:
- main branch: governance, templates, orchestrator, policy checks, docs UI
- pipeline branch: runnable application snapshot
- releases: immutable artifacts for each WI execution

Start here:
- docs/index.html (static docs UI)
- docs/FD_DOCUMENTATION.md
- backlog/milestones/MS-000-foundation.md

## Manual start from a new idea (Milestone Issue)

FD supports a manual start button so that a Milestone Issue is enough to begin automated work.

1) Create a GitHub Issue for the milestone.
   Preferred: include the Milestone ID in the title (example: "MS-01 Ship Daily major news summary").
   Alternative: include a body line "Milestone ID: MS-01".

2) Put your idea in the Issue body. It can be incomplete.
   The PM agent will normalize it into an executable v1 brief and will create Work Item issues.

3) Add repository secret:
   GEMINI_API_KEY

4) Run the workflow:
   Actions -> Orchestrate Milestone (Manual Start)

5) Provide input:
   issue_number = the GitHub Issue number for MS-XX (auto-assigned by GitHub)
   role_guide = ROLE_PM.txt

Outputs:
- A GitHub Release named FD-MS-XX-PM-YYYYMMDD-HHMMSS with artifact.zip and manifest.json
- One or more newly created Work Item Issues
- A comment posted to the Milestone Issue that lists the Release tag and created WI issues

## Work Item execution (Gemini -> Release -> optional pipeline branch update)

Use Actions -> Orchestrate Work Item (Gemini -> Release -> Pipeline).
This workflow takes a WI file path in the repo.
If you run WIs as Issues, add a WI runner that reads the Issue body.

## Secrets

Required for any Gemini agent run:
- GEMINI_API_KEY

Typical application secrets for a Telegram integration (used by the pipeline branch app, not by FD itself):
- TELEGRAM_BOT_TOKEN
- TELEGRAM_CHANNEL_ID


## Role based Gemini model selection

FD selects Gemini model per AI Agent role via `agent_guides/ROLE_MODEL_MAP.json`.

- Non-coding roles (PM, Tech Lead, Tech Writer, QA) default to `gemini-2.5-flash-lite` (lowest cost).
- DevOps defaults to `gemini-2.5-flash`.
- Coding and review roles (FE, BE, Reviewer) default to `gemini-2.5-pro`.

You can override at runtime:

- `GEMINI_MODEL` to force a single model for all roles.
- `GEMINI_ENDPOINT_BASE` to change the API base (default `https://generativelanguage.googleapis.com/v1beta`).

The endpoint used is:

`POST {endpoint_base}/models/{model}:generateContent`

API key is provided via header `x-goog-api-key`.
