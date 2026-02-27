# FD Auto (Two-Flow)

This drop-in adds two GitHub Actions workflows:

1) Build App From Milestone Issue (Manual)
- Input: issue_number (milestone issue)
- Output: pushes a new app branch (default: app-<ms-id>-<UTC timestamp>)
- Artifacts: plan + Gemini raw outputs + assembled app zip

2) Tune App Branch (Manual)
- Input: branch (app branch name)
- Runs dry-run + unit tests.
- If red, iterates: send failing logs + selected files to Gemini, receive a patch bundle, apply, commit, push.
- Stops when green or max_attempts reached.
- Artifacts: logs + Gemini prompts/outputs per attempt.

Secrets required:
- FD_BOT_TOKEN (PAT or GitHub App token with contents:write, issues:read, pull requests optional)
- GEMINI_API_KEY
Optional secrets:
- GEMINI_MODEL (default: gemini-2.5-pro)
- GEMINI_ENDPOINT_BASE (default: https://generativelanguage.googleapis.com/v1beta)

Notes:
- Workflows remain on main.
- App branches do NOT need workflows; main workflow checks them out.
