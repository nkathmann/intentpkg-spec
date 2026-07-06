---
name: intentpkg-extractor
version: 0.1.0
description: |
  Extract an intent package (intentpkg format v0.3.1+) from an existing
  application repository. Use whenever the user asks to extract, derive, or
  create an intentpkg / intent package from a repo or codebase, make an app
  "regenerable", or bring an existing/legacy/vibe-coded app under regenerative
  management. Input: a repo (and ideally a runnable instance). Output: a
  verified package plus an extraction report and open-questions ledger.
  The running original is ground truth; the package must pass its own gates
  against it.
---

# intentpkg-extractor: derive the package from the code

You are extracting declared intent from an application that was never
declared. Two disciplines govern everything:

1. **Extract what IS, not what should be.** The package describes the app
   as built, including its quirks. Anything that looks like a bug gets
   extracted faithfully AND logged as an open question; a human decides
   whether it is contract or defect. Silently "fixing" behavior during
   extraction is the cardinal failure.
2. **The original app is the gate for its own package.** A package the
   running original cannot pass is wrong by definition. Extraction is not
   done until the gates close against the source. When a gate fails against
   the original, repair the PACKAGE, never the app.

**Spec authority (fetch first):** the authoritative spec lives at
https://github.com/nkathmann/intentpkg-spec. At the start of every run:

1. `git clone --depth 1 https://github.com/nkathmann/intentpkg-spec` (or
   `git -C intentpkg-spec pull` if already present). Record the commit:
   `git -C intentpkg-spec rev-parse HEAD`.
2. Authority order: the cloned repo's `schemas/` (normative for L0, unknown
   keys rejected), `SPEC.md`, and `SPEC-UI.md` govern. The `schemas/` copy
   bundled in this skill directory is an offline-fallback SNAPSHOT only — use
   it when the network is unavailable, and say so in your report.
3. Runners: prefer `intentpkg-spec/tools/` from the clone
   (`validate_corpus.py`, `intentpkg_ui_runner.py`). If the behavioral runner
   is not in the clone, locate it locally as below.
4. Consult `schemas/` whenever writing or reading package YAML; do not rely
   on recall. Record the spec commit SHA you worked against in every
   deliverable (build report / provenance.lock history entry) — a package is
   only interpretable relative to a spec version.

The provenance.lock history entry MUST include `spec_commit:` (the SHA from step 1).

## Phase 0 — Survey

1. Inventory the repo: stack, entrypoints, schema/migrations, route
   definitions, test suite, seed data, schedulers, config/env handling.
2. Determine runability: can you start the app locally and seed it? Can you
   run its test suite? Record both; they set the ceiling on provenance
   quality (running app → `observed`; static reading → `inferred`).
3. Locate the runners (`tools/`, repo root, PATH). If absent, ask; do not
   produce an unverifiable package.

## Phase 1 — Extract, data-out

Work in this order, writing package files as you go:

1. **Data** (`data/entities.yaml`, `data/migrations/`): from migrations or ORM
   models. Schema is `observed` if read from migrations, `inferred` if
   reconstructed from queries. Record every FK, uniqueness, and nullability
   the code actually enforces. Flag columns nothing reads (open question).
2. **Interface** (`interface/api.openapi.yaml`): from route definitions and
   handler signatures. Status codes come from the code paths, not from
   convention — if the handler returns 404 where 403 is conventional, the
   package says 404 and the quirk is noted.
3. **Behavior**:
   - `behavior/invariants.yaml`: from validation logic, authz checks, DB
     constraints, and state machines found in code. Every invariant gets a
     `check:` probe; an invariant you cannot probe is prose and scores
     nothing — write it anyway, flagged.
   - `behavior/golden/`: port existing tests first (`observed`); where
     coverage is thin, derive cases by executing the running app with seed
     data and recording request → response → DB delta (`observed`), or from
     code reading (`inferred`). Include negative cases (authz denials,
     validation rejections) — extraction bias toward happy paths is the
     most common gap.
   - `behavior/jobs.yaml`: from schedulers, cron entries, queue consumers.
     Capture idempotency behavior as found, not as desired.
4. **Policy** (`policy/security.yaml`): authn mechanism, session/token
   handling, password hashing algorithm AND parameters as configured,
   role model, secrets handling. Read from code and config, not docs.
5. **Build** (`build/constraints.yaml`, `hints.yaml`): constraints are only
   what the business actually requires (runtime, DB engine if data depends on
   it); the incumbent stack goes in hints. Do not freeze the stack out of
   habit — that recreates the pet.
6. **Fixtures** (`fixtures.example.yaml`): from seed data and test factories,
   with real IDs and credentials that exist after seeding.

## Phase 2 — UI layer (if the app has one)

Runnable app: crawl every route at desktop and mobile viewports with
Playwright; serialize accessibility trees. Static-only: derive from templates
and stylesheets, and downgrade all UI provenance to `inferred`.

1. `ui/screens.yaml`: landmarks → regions; interactive nodes → components
   with roles; states you can induce with fixtures. Propose anchors from role
   + accessible name (provenance `extracted-proposed`).
2. **`ui/anchors.map.yaml`**: the original app has no `data-testid`s, so map
   every proposed anchor to a selector that finds it in the original (CSS or
   a11y-based). This map is used ONLY to verify the package against the
   original; regenerated builds must implement the anchors natively, and the
   map is deleted after the first conformant regeneration.
3. `ui/tokens.yaml`: cluster sampled computed styles (colors via perceptual
   distance, font sizes as the observed scale). High-spread clusters mean the
   original is internally inconsistent — pick nothing; log the cluster as an
   open question for a human to canonicalize.
4. `ui/copy.yaml`: verbatim strings of interactive and status elements.
5. `ui/flows/`: do NOT auto-extract journeys — inferred flows encode
   accidents as contracts. Emit one non-normative skeleton per screen (goto +
   presence expects) as scaffolding, clearly marked, for a human to promote.

## Phase 3 — Provenance and the ledger

- Every assertion carries provenance: `observed` (from running behavior or
  executable artifacts), `inferred` (from code reading), never `declared` —
  `declared` is reserved for human confirmation, which is not your call.
- Write `provenance.lock` with per-layer counts and an extraction history
  entry (date, repo commit hash, runability level).
- Write `OPEN-QUESTIONS.md`: suspected bugs preserved as-built, dead schema,
  unprotected endpoints, inconsistent styling clusters, invariants without
  probes, anything where you chose between plausible readings. Each entry:
  what you extracted, the evidence, the decision a human owes.

## Phase 4 — Close the gates against the original

1. `validate` the package (both runners). Fix coherence errors.
2. Start the original app, seeded. Run the behavioral runner against it in
   compat mode: the original predates the testing contract, so authenticate
   with real fixture credentials instead of header injection, verify jobs by
   triggering their real scheduler path or mark them `skip` with reason, and
   accept order-dependence (restart between runs) since `/__test/reset` does
   not exist. Record which gates are compat-verifiable vs. deferred to the
   first regenerated build (which WILL implement the testing contract — it is
   in the package).
3. Run the UI runner against the original using `anchors.map.yaml`.
4. Every failure is an extraction error. Repair the package; rerun; repeat
   until clean or every remaining failure is documented as an open question.

Honesty rules:
- Never weaken a gate to make the original pass; if the original is genuinely
  nondeterministic somewhere, say so in the report.
- Never emit an assertion without evidence you can cite (file:line, or a
  recorded request/response). Uncertain → `inferred` + open question.
- Coverage honesty: report the fraction of declared assertions that were
  machine-verified against the original, per layer.

## Phase 5 — Deliver

The package directory, the final verification report (JSON) from the run
against the original, `OPEN-QUESTIONS.md`, and a short extraction report:
repo commit, runability level, per-layer provenance counts, compat-mode gate
coverage, and the list of assertions deferred to first regeneration. The
package is ready for human confirmation review — the pass that upgrades
`observed`/`inferred` to `declared` — and then for the intentpkg-builder
skill to consume.
