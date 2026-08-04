# PampaPilot agent guide

## Mission

PampaPilot is a provider-neutral music-production agent for REAPER. Preserve the
boundary between reasoning and execution: an LLM proposes typed actions, Python
validates and orchestrates them, and the allowlisted Lua bridge is the only
component that writes to REAPER. Free-form model text is never executable.

## Architecture to preserve

- `src/pampapilot/`: deterministic Python engine, web app, MCP and analysis.
- `schemas/agent/v1/`: versioned contract between an LLM and PampaPilot.
- `reaper/PampaPilot_Bridge.lua`: allowlisted REAPER adapter and verification.
- `knowledge/`: versioned production knowledge and conservative starting points.
- `tests/`: offline contract and behavior tests.
- `media/`, `sessions/`, `.runtime/`: user/local state; never version or rewrite
  these as part of a development task.

Read `docs/architecture.md` and `docs/agent-protocol.md` before changing a
cross-component flow. Read the closest feature document before modifying a
producer or REAPER capability.

## Setup and validation

Windows x64 is the primary development platform.

```powershell
.\scripts\bootstrap.ps1
.\scripts\validate.ps1
```

For a focused test, use the project interpreter:

```powershell
.\.venv-pampapilot\Scripts\python.exe -m pytest tests\test_example.py -q
```

Run focused tests while iterating and `scripts/validate.ps1` before declaring a
task complete. Report exactly what ran and any remaining warnings.

## Git workflow

- Keep `main` stable. Development agents work on a dedicated branch/worktree.
- Local-model branches use `local-llm/<task>`; supervising Codex branches use
  `codex/<task>`.
- Never commit, push, merge, delete branches, or rewrite history unless the user
  explicitly requests it.
- Preserve unrelated and untracked user changes.
- Prefer a small, reviewable diff. Do not combine cleanup or refactoring with a
  feature unless required for correctness.
- Use the worktree as a creative sandbox: investigate alternatives, improve the
  proposed design, and make supporting refactors when they materially improve
  the requested result. Explain non-obvious choices in the completion report.

Create isolated work with `scripts/new-agent-worktree.ps1`.

## Safety boundaries

- Never place API tokens, LM Studio keys, credentials, stems, MIDI, renders, or
  local absolute paths in tracked files.
- `.agent-task.md` is an ephemeral task brief. Read it when present, never add it
  to Git, and do not treat it as authorization to commit or expand scope.
- Do not edit `.codex/config.toml`, `reaper/bridge_config.local.json`, `.runtime/`,
  `media/`, `sessions/`, or `.codex-remote-attachments/` automatically.
- Do not operate REAPER or its UI during code-only tests unless the user asks for
  a live integration test. Offline tests must not mutate a real project.
- Do not weaken action validation to accommodate an LLM response. Expand the
  versioned schema and validator deliberately, with negative tests.
- All REAPER writes require an allowlisted action, bounded inputs, a transaction,
  and read-back verification. Keep user approval semantics intact.
- Treat `reaper/PampaPilot_Bridge.lua`, IPC, concurrency, authentication,
  packaging, and agent-protocol changes as high risk and require supervisor
  review even when tests pass.

## Task routing

The local model is a development agent, not a command translator. It may reason
about the problem, inspect the whole repository, challenge the initial approach,
design alternatives, implement features, refactor within scope, and add tests or
documentation needed for a coherent result.

Architecture, cross-component behavior, difficult bugs, security,
process/IPC/concurrency, delicate refactors, and bridge changes may be explored
or prototyped by the local model in its isolated branch. They require supervising
Codex review before integration, rather than being forbidden upfront.

When a better result needs a material scope expansion, explain the tradeoff and
ask before committing to it. Small supporting changes that are safe, tested, and
clearly connected to the objective do not require a pause.

## Coding conventions

- Python 3.12 only; preserve the locked `uv` environment.
- Prefer deterministic code and typed/versioned JSON at agent boundaries.
- Keep provider-specific behavior inside provider adapters.
- Reuse the existing analysis and knowledge engines rather than duplicating
  musical rules in prompts or UI code.
- Add regression tests for every bug fix and contract tests for every new action.
- User-facing text is Spanish unless the surrounding surface is deliberately
  English; identifiers and schemas remain stable and technical.

## Completion report

State the outcome first, then list changed files, validation performed, and any
manual REAPER or listening test still required. Never claim a REAPER action or
audio result was verified when only an offline test ran.
