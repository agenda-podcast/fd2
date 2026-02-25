# Milestone

Milestone ID: MS-000
Title: Establish FD governance and automation skeleton

## Intent Brief

Target user: Contributors and AI agents delivering FD pipeline outputs
Problem: Need deterministic automation to turn WIs into runnable pipeline branch updates and Release artifacts
Success signal: main branch has governance + runner + CI; pipeline branch can be generated and verified
Constraints: ASCII-only, <=500 lines per non-table code file, no ellipses, releases store artifacts

## Scope Boundary

In scope:
- FD governance docs and templates
- Policy checks in CI
- Orchestrator runner that publishes to Releases and updates pipeline branch

Out of scope:
- Any other products

## Work Items

- WI-001 (docs foundation)
- WI-002 (orchestrator runner and release publishing)
- WI-003 (seed pipeline branch application)

## Risks and Mitigations

- Risk: CI flakiness. Mitigation: deterministic scripts and stable outputs.

## Acceptance Memo Criteria

- main branch passes CI and docs UI loads locally.
- pipeline branch can be created and validated via workflow.
