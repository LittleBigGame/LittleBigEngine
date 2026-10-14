# Antigravity onboarding — ModEngine / LittleBigEngine

This ZIP preserves the supplied **Python engine source** and adds project agent configuration, design documentation, baseline tests and a single first-message prompt. It is not a rewritten engine.

## Quick start
1. Extract the ZIP and open the **`ModEngine` folder itself** as Antigravity's workspace root (the directory containing `AGENTS.md`).
2. Use **Antigravity 2.0 or the CLI** for native custom concurrent subagents. The older standalone IDE may load rules/skills but may lack custom-subagent execution.
3. In Antigravity 2.0 choose the custom primary agent **`lbe-lead`** via the agent picker. In the CLI use the `/agents` panel or documented `agy --agent lbe-lead` selector. Check that roles are discovered before assuming they run.
4. Paste the full text from `ANTIGRAVITY_START_PROMPT.md` into a new conversation with `lbe-lead`.
5. Ask the lead to verify effective project rules and subagent availability. **The first run is governance validation only — no engine rewrite.**
6. After reviewing the documented proposed ADRs, discuss and approve the smallest first implementation slice. The lead delegates the approved task and verifies its outputs.

## Roles present
- `lbe-lead`: conversational architect and coordinator; available as primary agent.
- `lbe-implementer`: bounded code changes.
- `lbe-test-engineer`: independent tests.
- `lbe-architect-reviewer`: independent, no-edit design audit.
- `lbe-performance-reviewer`: optional measurement-led performance audit.

## Reusable skills
- `/lbe-change` for controlled implementation.
- `/lbe-review` for no-edit code/architecture evaluation.

## Important limits
- Rules and role descriptions guide the agent; **they are not operating-system write permissions or a proof of compliance**.
- Git worktrees, approvals, isolated branches and GitHub required status checks must be configured in your actual local/remote Git environment. They are not enabled simply by extracting this ZIP.
- Actual native subagent delegation requires supported Antigravity versions and the runtime tool `invoke_subagent`. On a non-supporting IDE, agents should use sequential role-based review, not claim to have spawned workers.
- The archive included `.venv`, `.venv1`, `.idea`, `.git` skeleton and `__pycache__` bytecode. These **generated/machine-specific folders are excluded** from this new package; source files, example world data and application entrypoints are kept. Your original ZIP remains unchanged.
- Use your own local venv: `python -m venv .venv` then install `pytest` and `ruff` if needed. The source uses Python **3.13+** syntax.
- Existing `LBE/Queue.py` is broken; the tests label this as a known defect, not success.

## Inspect governance
- Root `AGENTS.md`: always-on rules.
- `docs/ARCHITECTURE.md`: target model, proposed details clearly labeled.
- `docs/CURRENT_STATE.md`: audited actual prototype and known problems.
- `docs/DECISIONS.md`: accepted design directions and open decisions.
- `docs/CODING_STANDARDS.md`: **draft** initial coding principles, not a claim of previously existing rules.
- `docs/TESTING.md`: present testing gates and future requirements.
- `docs/EXISTING_CODE_REVIEW.md`: detailed evidence-based review.

## Quality checks
```bash
python -m pip install pytest ruff
python -m pytest -q
python tools/check_architecture.py
ruff check tools tests
```

The repository also contains `.github/workflows/quality.yml` to run checks when pushed to GitHub. Enable branch protection/review requirements manually in GitHub if you want them enforced for merges.

## Official documentation
- https://www.antigravity.google/docs/rules/
- https://www.antigravity.google/docs/subagents/
- https://www.antigravity.google/docs/skills/
