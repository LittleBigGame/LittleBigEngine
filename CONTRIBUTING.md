# Contributing and GitHub workflow

This repository should contain the engine code, tests, and documentation that
helps someone run and use the project. Keep the history useful to a future
human contributor.

Do not commit AI conversations, prompts, model output, generated analysis, or
other AI working documents. They stay local only. Use `local-ai/`, `.local-ai/`,
or `ai-private/` for that material; these folders are ignored by Git. Before
committing, always inspect what will be included with `git status` and
`git diff --staged`.

## What belongs in Git

- Engine and game source code.
- Tests that demonstrate intended behaviour or prevent a regression.
- User-facing documentation: how to install, run, use, and contribute to the
  project, plus architecture/API documentation when it helps users.
- Small, necessary project assets that the game needs to run.

## What stays local

- AI chats, prompts, planning notes, and raw model output.
- Temporary experiments, screenshots, logs, local builds, and throwaway assets.
- Personal editor/IDE settings and virtual environments.

## One change, from issue to merge

1. **Create a GitHub issue.** Describe the problem, expected result, and a
   short way to reproduce it. A feature request should state the user outcome,
   not just an implementation idea.
2. **Create a branch from the current default branch.** Give it a focused name,
   for example `fix/viewport-selection` or `feature/sprite-import`.
3. **Make the change on that branch.** Keep it scoped to the issue. Update
   tests and user documentation whenever behaviour changes.
4. **Run the relevant checks.** For this project, run:

   ```powershell
   .\.venv\Scripts\python.exe tests/run_suite.py -v
   ```

   On Linux/macOS use `.venv/bin/python tests/run_suite.py -v`. The runner
   isolates preferences and analysis caches from your normal editor state.

5. **Review the change before committing.**

   ```powershell
   git status
   git diff
   git diff --staged
   ```

   Verify that no local AI material or unrelated generated files are included.
6. **Commit to the branch.** Use an imperative, focused message such as
   `Fix viewport selection without moving entities`.
7. **Push the branch and open a pull request.** Link the GitHub issue, explain
   the behaviour change, list the tests run, and include screenshots only when
   they help review a visual change.
8. **Review and merge.** Resolve feedback, ensure checks pass, then merge the
   pull request. Delete the remote branch when it is no longer needed.

Do not develop directly on the default branch. Each issue gets a branch; each
branch is reviewed and merged through a pull request.

## If Git blocks this folder on Windows

Git can report “detected dubious ownership” for a repository on a drive that
does not record ownership. Mark only this repository as safe, then retry:

```powershell
git config --global --add safe.directory "F:/Little Core"
```

Do not use a wildcard safe-directory setting.
