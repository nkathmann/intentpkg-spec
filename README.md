# intentpkg — Intent Package Format (working name)

**Status: v0.3.1-draft. Working name — the format will be renamed before 1.0.**

An intent package is the durable, regenerable specification of an application:
business intent, data contracts, interface contracts, executable behavioral
contracts, a UI contract, integrations, and org policy bindings — with
per-assertion provenance. The thesis: **the spec is the application; the code
is a build artifact**, rebuilt on a cadence from the package under current
dependencies and policy, and trusted because it passes the package's gates —
not because the generator is trusted.

v0.3 added the **UI contract layer** (`ui/`): screen structure and stable
anchors, design tokens, verbatim copy, and journey-shape flows, verified in a
real browser. The layer exists because behavioral fidelity alone lets a
rebuild reshuffle the interface under its users. Its rule: structure, tokens,
copy, and journeys are intent; pixels are build artifacts. Normative text in
`SPEC-UI.md`.

Two kinds of tools implement this format:

- **Extractors** analyze an existing application (source, schema, traffic) and
  emit a package. Their obligations: honest provenance, `UNKNOWN` over
  guessing, evidence pointers, quirks recorded as contract.
- **Builders** read a package and produce a running application. Their
  obligations: contracts are binding, hints are disposable, quirks are
  preserved not fixed, data stores are never touched, contract files are
  transpiled into source rather than re-typed, and the build isn't done until
  the conformance gate passes.

Reference implementations of both ship in `skills/` as Claude Code skills; any
agent that reads the format is a friend.

## Conformance levels

```
L0 Valid        files parse and satisfy schemas/ (unknown keys rejected);
                provenance present
L1 Coherent     cross-references resolve: goldens -> OpenAPI, flows -> anchors,
                components -> copy keys, hooks -> jobs, db assertions -> tables
                the migrations actually create, migrations well-formed
L2 Verified     behavioral gates pass against a RUNNING build: golden cases,
                invariant probes, database checks
L3 UI-Verified  interface gates pass against a running build in a real
                browser: structure and anchors, token bindings and palette
                conformance, verbatim copy, journey-shape flows, axe rules
L4 Governed     build satisfies policy bindings and emits attestation
```

Fidelity and probe coverage are reported side by side at every level.
Equivalence between builds extends exactly as far as the contract's coverage —
no further. Coverage is the honest number; treat any fidelity score without it
as marketing.

Two principles govern how reports are consumed. **The JSON report is the
artifact of record**: prose never overrides it, a failing gate stays failed no
matter how a builder characterizes it, and only the package owner can waive a
gate — by changing the package. **The verification adapter is part of the
trusted computing base**: the fixtures `db.command` must execute package
queries verbatim; an adapter that translates or rewrites queries falsifies
gate evidence, and green results obtained through one are void.

## Repository layout
```
SPEC.md              normative specification (RFC 2119 language)
SPEC-UI.md           normative UI contract layer (screens, tokens, copy,
                     flows, gate semantics, baseline/blessing protocol)
schemas/             JSON Schemas for every package file — normative for L0,
                     unknown keys rejected (validation targets for both
                     extractors and builders)
examples/            canonical example packages: sumhub.intent (complete
                     minimal package, ~15 files) and helpdesk.intent (the
                     flagship — full UI layer, 7 screens, 8 flows, 59 anchors)
tools/               reference runners (behavioral L0–L2, UI L3) and
                     validate_corpus.py; tools/harness/ is the runner's own
                     conformance suite — a reference-conformant mock build
                     plus a planted-violations mode (see its README for the
                     two checks that define a working runner)
skills/              reference extractor and builder as Claude Code skills;
                     they clone this repo for authority and define "done" as
                     gate output
proposals/           numbered design proposals for spec evolution
                     (0001: system composition; 0002: async & temporal
                     contracts) plus GAPS.md, the honest coverage-gap
                     register with design sketches
```

## Quickstart

```bash
# validate a package statically (L0 + L1, schema-enforced)
python3 tools/intentpkg_ui_runner.py validate examples/helpdesk.intent

# verify a running build (requires playwright + chromium for L3)
python3 tools/intentpkg_runner.py    verify examples/helpdesk.intent --base-url http://localhost:3000 --fixtures fixtures.yaml
python3 tools/intentpkg_ui_runner.py verify examples/helpdesk.intent --base-url http://localhost:3000 --fixtures fixtures.yaml

# or exercise the runners against the built-in harness (no app of your own needed):
#   see tools/harness/README.md
```

Every report records the package revision and spec commit it ran against; a
report that can't say what it verified is not evidence.

## Empirical grounding

The format has been exercised in both directions, and every change in it was
forced by an experiment, not designed in the abstract.

**Extraction (code -> package -> code).** Three real AI-generated applications
(Next.js/Supabase, Next.js dual-store SQLite+Postgres, Java 21/Spring Boot)
were hand-extracted and regenerated from their packages alone, verified by the
conformance gate: fidelity 1.0 in all captured reports, L2 probe coverage
0.76–0.87.

**Authoring (package -> code, no original).** A greenfield package
(helpdesk.intent: three roles, specialty routing, attachments, a scheduled
archive job) was built by a coding agent from the package alone: 104
behavioral gates, zero failures, 94% of declared assertions machine-verified
on the first attempt.

**UI gates.** The L3 runner holds fidelity 1.0 across 700+ gates on a
conformant reference build and catches all planted contract breaches (missing
anchors, off-palette colors, reworded copy, injected dialogs, broken focus
order) with zero false positives — see `tools/harness/`.

**Incremental regeneration.** A package revision (two new anchors, two new
flows) was applied to a previously verified build by the reference builder
skill: gates passed on the first live attempt with zero repair iterations,
and rerun reports were byte-identical. Spec diff in, build diff out, gate
confirms — the steady-state lifecycle motion.

**Cross-model builds — and a rejection.** A different model family (DeepSeek
V4 Pro) executed the reference builder skill against the package. Its first
build drove both gate suites to fidelity 1.0 — and was rejected: it had built
on SQLite with an invented schema instead of applying the declared PostgreSQL
migration, and its DB adapter translated the package's queries in flight so
the gates could pass. Every green DB gate was testing rewritten evidence. The
rejection produced the engine pin and the adapter-transparency rule above. The
rebuild on PostgreSQL passed all 106 behavioral gates; its seven remaining UI
failures decomposed under review into two genuine build defects, one fixtures
gap, and one package defect — each promoted into the contract or the runner
the same day. A conformance regime earns credibility with its first refusal,
not its first pass.

**The instructive failure.** One generated build passed every declared gate at
fidelity 1.0 and was still unusable: its ticket rows and filter tabs rendered
but did nothing, in exactly the region the declared coverage did not reach.
The gap was promoted into the contract (interactivity flows with positive and
negative assertions) the same day. That is the intended failure mode of the
whole approach: visible, localized, and convertible into permanent coverage —
which is also why the coverage number matters as much as the fidelity number.
Seven such promotions happened in the format's first week, from two model
families independently probing for the softest spot; the provenance ledger in
the flagship package records each one, dated.

## License
Apache-2.0 (spec text and schemas).
