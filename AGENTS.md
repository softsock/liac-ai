# Repository Guidelines

## Project Structure & Module Organization

Code lives in `src/vtuber/`: `contracts/` defines immutable data and ports, `runtime/` owns SQLite and task lifecycle, and `minds/` contains fake/LM Studio adapters and `character.md`. `context.py` compiles model-independent messages. `app.py` wires dependencies; `cli.py` is the inspector. Critical checks live in `tests/`. Local data defaults to ignored `.data/`.

Read relevant sections of `docs/PROJECT_BLUEPRINT.md`, milestone implementation reports and nearest module `AGENTS.md` before editing. Memory, behavior and external interfaces remain future milestones.

## Build, Test, and Development Commands

Use Python 3.12+ and a virtual environment. HTTPX is the only core direct runtime dependency; real Fast also uses optional `.[nemotron]`. No formatter or linter is configured.

- `python -m pip install -e .` — install the package in the active environment.
- `python -m vtuber` — run the fake-backed CLI.
- `python -m vtuber --fast-backend lmstudio --endpoint URL --model ID --tokenizer PATH` — stream from loaded Nemotron; see README for the pinned tokenizer.
- `python -m unittest discover -s tests -v` — run critical invariant checks.
- `git diff --check` and `git status --short` — inspect whitespace and changed/untracked files.

## Coding Style & Naming Conventions

Keep Markdown concise, with descriptive headings and repository-relative links. Preserve blueprint status labels: `DECIDED`, `PROVISIONAL`, `EXPERIMENT`, and `FUTURE`.

Use four-space indentation, `snake_case` functions/modules, `PascalCase` classes and public-interface type hints. Prefer the standard library and small cohesive modules. Contracts cannot import infrastructure. Runtime imports model ports, not concrete adapters; only the composition root wires implementations. Keep task cancellation explicit and transactions short.

## Testing Guidelines

Use stdlib `unittest`; no coverage threshold. Name tests `test_*.py`. Focus on atomicity, idempotency, revisions, recovery, context boundaries and stream cancellation. Verify milestone behavior through the CLI and record actual results. Fake/transport checks do not establish live provider compatibility.

## Commit & Pull Request Guidelines

History uses imperative subjects, sometimes prefixed with `feat:` or `docs:`. Use a concise, specific subject. Every commit must include:

```text
Co-authored-by: softsock <109231668+softsock@users.noreply.github.com>
```

Credit softsock in PR descriptions too. Describe behavioral effects, affected invariants, failure cases, actual checks, and blueprint changes; link relevant issues. Create PRs only when explicitly requested.

## Agent & Configuration Rules

Never use GPT-6 Astra for subagents. Keep changes within the requested milestone; future blueprint items are not current requirements. Keep secrets and private runtime data out of Git and diagnostics. Do not modify Loonyball, deploy, or install large services without an explicit request.

M2 adds optional Luna via the pinned SDK-only vendor under `vendor/omp-rpc`. Install with `python -m pip install -r requirements-luna.txt`; fake mode requires neither SDK nor credentials. Deep returns versioned results; Runtime alone commits decisions and acknowledgement.
