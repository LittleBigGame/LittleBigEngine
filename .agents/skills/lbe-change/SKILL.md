---
name: lbe-change
description: "Use for any LittleBigEngine feature, bugfix or refactor that changes engine code: scope approval, bounded implementation, separate verification, architecture review and evidence-based handoff."
---

# LBE controlled change

## Choose the path
- **Brainstorming/design only:** discuss; don't edit code or spawn implementer. Record an ADR proposal only when asked.
- **Small approved fix:** inspect affected files, implement minimally, run tests, do an independent review pass; delegating is optional.
- **Feature/refactor with clear acceptance:** send a self-contained task to `lbe-implementer`; after implementation, use `lbe-test-engineer` and `lbe-architect-reviewer` independently where supported.
- **Architecture breaking change:** stop before implementation; explain alternatives, compatibility and migration; obtain approval and create an Accepted ADR first.

## Preparatory check
Read `AGENTS.md`, `docs/CURRENT_STATE.md`, `docs/CODING_STANDARDS.md`, `docs/DECISIONS.md` and only the relevant code. Identify current behavior and smallest necessary behavior change. Propose: affected files, public interfaces, dependency boundaries, tests and rollback.

## Delegation brief template
```text
Objective:
Current state (verified in code):
Approved scope and editable file paths:
Do not touch:
Architecture invariants / relevant ADRs:
Inputs / interfaces / migration:
Acceptance tests, including failures:
Commands permitted:
Deliver: changed files, actual results, blockers:
```

## Verification and review
Run `python -m pytest -q`, `python tools/check_architecture.py` and `ruff check tools tests` as applicable. If tools are unavailable, report `NOT RUN`, not `PASS`. Reviewer independently classifies issues and challenges unnecessary abstractions. Keep conflicting edits isolated and inspect diffs before merging.

## Complete / stop
Report behavior, tests, performance evidence if relevant, known failures and design risks. Stop and escalate on broader scope, new dependencies, public contract breaks or persistent format changes. No quiet governance updates.
