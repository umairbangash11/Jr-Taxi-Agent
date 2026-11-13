---
id: 24
title: Git commit PR workflow no remote
stage: general
date: 2026-11-13
surface: agent
model: claude-opus-5-5
feature: none
branch: 001-phase1-saft-reader
user: umairbangash11
command: /sp.git.commit_pr
labels: ["git", "commit", "pr", "github"]
links:
  spec: null
  ticket: null
  adr: null
  pr: null
files:
 - history/prompts/general/23-final-check-commit-phase1-push-blocked.general.prompt.md
 - history/prompts/general/24-git-commit-pr-workflow-no-remote.general.prompt.md
tests:
 - none (git-only workflow)
---

## Prompt

/sp.git.commit_pr — Your task is to intelligently executes git workflows to commit the work and create PR following your Principles (full agentic git workflow command text: gather context, decide branch strategy, generate commit/PR content, execute, validate, invoke human on blockers).

## Response snapshot

Context: on feature branch 001-phase1-saft-reader, Phase 1 already committed (dcbae6e);
only untracked change was PHR 23. Committed PHRs 23–24 as a docs(history) commit.
Push and PR blocked: no git remote configured and GitHub CLI (gh) not installed.
Invoked human validator with options (install gh, or provide an empty repo URL).

## Outcome

- ✅ Impact: Working tree clean; history records committed locally.
- 🧪 Tests: none (git-only per workflow rules).
- 📁 Files: 2 PHR files.
- 🔁 Next prompts: provide remote URL or install gh → push both branches, open PR to main.
- 🧠 Reflection: Remote/gh blocker unchanged since previous turn.

## Evaluation notes (flywheel)

- Failure modes observed: no remote, no gh CLI
- Graders run and results (PASS/FAIL): n/a
- Prompt variant (if applicable): null
- Next experiment (smallest change to try): null
