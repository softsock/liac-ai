# LILAVEL-ARAS-M3C-2 — Core dependency direction guard

Status: ACTIVE
Updated: 2026-09-06
Repository / checkout: `C:\Lilavel` - canonical Lilavel repository checkout
Branch / worktree: `feat/conversation-core`
Base commit: `32448237b542e3144c88bcd6242ea08c49188a72`
Last checkpoint commit: `32448237b542e3144c88bcd6242ea08c49188a72`

## Goal

Implement the smallest deterministic Core-side structural test that fails
when `apps/core` directly imports or declares a runtime dependency on the
verified Discord package/namespace.

## Scope

- A narrow AST-based import-direction guard in the existing Core test area.
- The verified forbidden roots: `lilavel_discord_edge` and `discord`.
- Recursive inspection of Python source under `apps/core/src/lilavel_core` only.
- Reversible adversarial proof, package validation, and read-only review.
- This compact work record.

## Non-goals

- No package-boundary redesign, runtime or product change, or API refactor.
- No semantic ownership proof, model-sidecar ownership check, or M3C-3
  diagnostics-redaction work.
- No hooks, rules, CI, sandbox policy, generic architecture framework, import
  graph engine, or new dependency.
- No dynamic-import analysis unless current Core code makes it necessary.

## Exit criteria

- Direct Core imports of both verified Discord roots fail for `import X` and
  `from X import Y` forms where relevant.
- Comments and strings do not trigger violations; nearby non-Discord imports
  remain allowed.
- No runtime/source/product semantics or heavyweight tooling changes.
- Adversarial failure proof passes, the mutation is fully reverted, and the
  targeted plus required Core validation passes.
- Independent review finds no material issue and limitations/UNVERIFIED
  evidence are recorded honestly.

## Current implementation state

`RESULT`: the guard is implemented in
`apps/core/tests/test_architecture_boundaries.py`. It walks only
`apps/core/src/lilavel_core/**/*.py`, parses Python with the standard-library
`ast` module, and rejects absolute import roots `discord` and
`lilavel_discord_edge` for both `import X` and `from X import ...` forms.
Comments, strings, relative imports, Core self-imports, tests, fixtures, and
unrelated packages are outside the forbidden set. No production source or
runtime behavior changed.

Manifest-level dependency checking was evaluated and intentionally not added:
the Core runtime dependency list is currently empty, and the accepted M3B
OWN-01 contract selects this package-local AST guard rather than a second
distribution-name parser. A manifest-only future dependency is therefore an
explicit limitation of this mechanism.

## Established results

- `RESULT`: the current Core source passes the guard; the synthetic tests
  prove both absolute import forms and both verified Discord roots are
  rejected while comments, strings, and a Core import remain allowed.
- `RESULT`: a disposable Core source mutation containing `import discord`
  failed the guard with the exact relative file, line, and forbidden import;
  the mutation was removed and the restored targeted suite passed.
- `RESULT`: no new package dependency, hook, rule, CI configuration, runtime
  source, product behavior, or architecture framework was added.

## Remaining work

- Human review and an explicit checkpoint/commit decision remain. No in-scope
  implementation work remains.

## Next safe action

Hand M3C-2 to human review for checkpoint approval. After acceptance, proceed
to the separately recorded M3C-3; do not mix diagnostics-redaction work into
this item.

## Validation

- preflight/topology: `PASS` - actual branch, HEAD, clean starting worktree,
  package manifests, source imports, architecture, and M3B/M3C-1 state checked.
- structural guard: `PASS` - from `apps/core`, targeted AST guard suite (3
  passed), Ruff check, and Ruff format check.
- adversarial proof: `PASS` - disposable `import discord` Core-source mutation
  failed with a named violation; mutation was fully removed and the restored
  targeted suite passed.
- Core package validation: `PASS` - from `apps/core`, `uv sync --locked`,
  `uv lock --check`, Ruff check/format, Pyright, and full
  `uv run --locked pytest` (118 passed on Windows).
- whitespace/state checks: `PASS` - `git diff --check` and explicit trailing-
  whitespace inspection of new/relocated files passed; temporary proof file is
  absent.
- independent read-only review: `PASS` - path resolution, namespace matching,
  import-form coverage, comment/string behavior, scope, and absence of runtime
  changes reviewed; no material issue found.
- provider/live/Discord/restart/full end-to-end evidence: `UNVERIFIED` - not
  claimed and not required for this deterministic guard.

## Limitations

- The guard does not detect manifest-only Discord dependencies, dynamic import
  calls, subprocess/provider behavior, reverse dependency violations outside
  Core source, or semantic ownership inversion.
- It does not scan Core tests, fixtures, documentation, unrelated packages, or
  generic names that are not the verified roots.

## Handoff

- Git/checkout state: `feat/conversation-core` at
  `32448237b542e3144c88bcd6242ea08c49188a72`.
- Uncommitted changes: `apps/core/tests/test_architecture_boundaries.py`, this
  M3C-2 record, and the separate M3C-1 active-to-completed record correction.
  Nothing is staged; no unrelated implementation paths are present.
- Exit criteria: `SATISFIED` for the deterministic source-import guard and
  review scope; manifest-only, provider/live, Discord, restart, and full
  end-to-end evidence remain `UNVERIFIED` or explicitly limited above.
- Blockers/unknowns: none identified.
- Next safe action: human review/checkpoint; then a separately recorded M3C-3.
