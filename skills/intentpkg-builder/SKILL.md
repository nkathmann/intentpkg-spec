---
name: intentpkg-builder
version: 0.1.0
description: |
  Build or regenerate a complete application from an intent package (intentpkg
  format v0.3.1+). Use whenever the user asks to build, rebuild, or regenerate
  an app from a *.intent directory or tarball, references an intentpkg
  manifest, or says "regenerate from the package". The package is the complete
  and only specification; this skill defines how to consume it reliably. Done
  is defined by verification gates, never by self-assessment.
---

# intentpkg-builder: consume an intent package

You are building an application from a declared-intent package. The generated
code is a disposable artifact; the package is the source of truth. Your output
will be verified by automated gates against a running instance. **You are not
done until the gates say you are done.**

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

The final build report MUST include `spec_commit:` (the SHA from step 1).

## Phase 0 — Inventory and validate

1. Locate the package root (directory containing `manifest.yaml` with
   `format: intentpkg/*`). Extract tarballs first.
2. Locate the runners. Look in order: `tools/` beside the package,
   `intentpkg_runner.py` / `intentpkg_ui_runner.py` on PATH or in the repo
   root. If absent, STOP and ask the user for them — do not build unverifiable.
3. Run `validate` on the package (`intentpkg_ui_runner.py validate <pkg>` and
   the behavioral runner's validate). If the package itself is incoherent,
   STOP and report the errors; never "fix" the package silently to make your
   build pass.

## Phase 1 — Read in this order

`manifest.yaml` → `intent.md` → `data/` (entities, migrations) →
`interface/` (OpenAPI, surfaces) → `behavior/` (invariants, golden cases,
jobs, scenarios) → `policy/` → `ui/` (screens, tokens, copy, flows) →
`build/` (constraints, hints) → `fixtures.example.yaml` → `provenance.lock`.

Bindingness rules — these are format semantics, identical for every package:

- Everything declared is contract. Prose in `intent.md` explains; YAML binds.
- `build/constraints.yaml` bounds your stack choices; `hints.yaml` advises.
- The data layer is sacred: implement migrations exactly as declared; never
  invent schema the migrations don't create.
- Testing contract: `TEST_AUTH=1` honors the `x-test-principal` header as the
  authenticated principal; `TEST_HOOKS=1` exposes
  `POST /__test/jobs/<job-id>/run` for every job in `behavior/jobs.yaml` and
  `POST /__test/reset` (reseed fixtures). Implement all three. Gates depend
  on them; production builds ship with both env vars off.
- If `ui/` exists: anchors, tokens, copy, screen structure, states, focus
  order, and flow shape are binding. `ui_substrate.token_binding` (usually
  css-variables at `:root`, named `--color-<name>` etc.) is normative. No
  colors outside the declared palette (white-mix tints of declared tokens are
  legal); no font sizes outside the declared scale; forbidden portal accents
  are absolute. No dialogs, steps, or screens on a declared flow path that the
  flow does not declare.

## Phase 2 — Transpile the contracts (do not re-type them)

Before writing any application code, generate source artifacts FROM the
contract files, and make application code consume the generated artifacts:

1. `ui/tokens.yaml` → a generated stylesheet or theme file defining every
   token as a CSS custom property at `:root`. All styling references
   variables; no hardcoded colors, radii, or font sizes anywhere in your code.
2. `ui/copy.yaml` → a generated strings module. UI code imports strings by
   key; a string literal for user-facing bound copy in a component is a
   defect.
3. `ui/screens.yaml` → a generated anchors module (constants keyed by anchor
   id). Every `data-testid` in templates/components references a constant.
   Also emit, for your own use, a per-screen checklist: route, regions with
   landmarks, components with roles, states with their fixtures, focus order.
4. `interface/*.openapi.yaml` → route stubs or a router table, so the API
   surface is generated, not remembered.

Re-typing a value that exists in a contract file is the root cause of most
gate failures. Derive; never transcribe.

## Phase 3 — Implement

Work data-out: schema and migrations → domain rules and invariants → API →
jobs → UI screens (satisfying the per-screen checklist) → flows as manual
smoke tests. Consult `behavior/golden/` while implementing each endpoint; the
golden cases are the acceptance semantics, including exact status codes and
DB side effects. Seed `fixtures.example.yaml` data exactly (IDs matter; gates
reference them).

## Phase 4 — The verify-repair loop (this defines "done")

1. Start the app with `TEST_AUTH=1 TEST_HOOKS=1`.
2. Run the behavioral runner (L0–L2) with `--json`.
3. Run the UI runner: `intentpkg_ui_runner.py verify <pkg> --base-url <url>
   --fixtures <fixtures> --json` (L3, requires Playwright + chromium).
4. Parse the JSON. Every failure names the gate, the expectation, and the
   observation. Repair the build (never the package), rerun the affected
   runner, repeat.
5. Stop when both reports show zero failures, or after 5 full repair
   iterations. If stopping unclean, report the final numbers and the
   remaining failures verbatim.

Honesty rules:
- Never weaken, skip, or reinterpret a gate to pass it. If a gate looks wrong,
  say so in the report; the package owner decides.
- Never claim completion without attaching both final JSON reports.
- Keep the first-attempt reports as well as the final ones; both get delivered
  (first-attempt fidelity is data the package owner wants).

## Phase 5 — Deliver

The runnable app with a README (run instructions, env vars), a
`fixtures.<build>.yaml` mapping real seeded IDs/credentials with a working
`db.command` adapter, and the verification reports (first attempt + final).
