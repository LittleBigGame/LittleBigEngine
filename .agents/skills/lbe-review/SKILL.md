---
name: lbe-review
description: "Use when asked to audit existing LittleBigEngine code or a proposed diff for correctness, code quality, boundary violations, debt or implementation readiness, without automatically rewriting code."
---

# LBE review-only workflow

Read current-state and architecture docs. Inspect the precise requested files/diff and immediate dependencies; avoid full-codebase reading without justification. Separate `observed`, `reproduced`, `hypothesis` and `proposed`. Prioritize actual correctness bugs, consistency, architecture erosion and hotspot costs. Use precise file locations and reproducible commands. Return severity-ranked findings with minimal remediation and a summary of what is worth keeping. **Do not modify production code in review mode.**
