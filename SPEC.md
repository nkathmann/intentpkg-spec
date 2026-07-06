# intentpkg Specification, v0.3.1-draft

> v0.3.1 adds the UI contract layer (`ui/`: screens, tokens, copy, flows) and
> conformance level L3 UI-Verified; Governed renumbers L3 -> L4. UI layer
> normative text: SPEC-UI.md. JSON Schemas in schemas/ are normative for L0.

Working name: `intentpkg`. Format identifier: `intentpkg/v0.3.1`. Packages
declaring `intentpkg/v0.1` remain valid; v0.2 changes are additive.

The key words MUST, MUST NOT, SHOULD, SHOULD NOT, and MAY are to be
interpreted as described in RFC 2119.

---

## 1. Purpose and model

An **intent package** is the durable specification of an application. The
package — not the source code — is the asset an organization versions,
reviews, governs, and keeps. Application code is a **build artifact**,
regenerated from the package on a cadence or on demand, under
currently-approved dependencies and organizational policy.

Because generation is nondeterministic, **trust comes from the gate, not the
generator**: a package carries executable contracts, and any candidate build
that satisfies them is acceptable. Equivalence between builds is *defined by
the contract* and extends exactly as far as the contract's coverage — no
further. Coverage is therefore a first-class, reported metric (§9).

Two tool roles implement the format:

- an **extractor** derives a package from an existing application;
- a **builder** produces a running application from a package.

A package MUST be sufficient for a competent builder to produce a conformant
build without access to the original source. This sufficiency claim is scoped:
see §3 (scope) and §9 (conformance and coverage).

## 2. Package layout

A package is a directory named `<app-id>.intent/`:

```
<app-id>.intent/
├── manifest.yaml                # identity, envelope, scope, datastores, testing contract
├── intent.md                    # business intent — prose, human-first
├── data/
│   ├── entities.yaml            # entity/schema contract (the sacred layer)
│   ├── classifications.yaml     # optional: PII/retention/residency per field
│   └── migrations/              # ordered history; NEVER regenerated
├── interface/
│   ├── api.openapi.yaml         # programmatic surface (OpenAPI 3.x + extensions, §6)
│   ├── surfaces.yaml            # human-facing surfaces (screens, pinned elements)
│   └── unscoped-surfaces.yaml   # optional: inventoried, uncontracted surfaces
├── behavior/
│   ├── invariants.yaml          # properties that must hold (+ optional probes)
│   ├── scenarios/*.feature      # Gherkin acceptance sequences
│   └── golden/*.cases.yaml      # concrete request/response/db-state cases
├── integrations/
│   └── integrations.yaml        # external systems; secret REFERENCES only
├── policy/                      # ORG-INJECTED; read-only to the app owner
├── build/
│   ├── constraints.yaml         # binding: languages, frameworks, deny-lists
│   └── hints.yaml               # non-binding preferences; disposable
├── fixtures.example.yaml        # template for verification fixtures
└── provenance.lock              # generated assertion ledger + confirmation queue
```

Rationale for a directory over a single file: layers have different owners,
stability classes, and change-control rules; directories diff and review
cleanly and map onto CODEOWNERS-style governance.

## 3. Manifest (`manifest.yaml`)

Required fields: `format`, `app.id`, `envelope`, `versions`.

- **`envelope`** declares the application class the package claims
  (`internal-web-app/v1` in this version: web UI and/or HTTP API,
  CRUD-plus-workflow logic, relational-ish datastores, bounded integrations,
  single-tenant, no realtime, no in-process ML pipelines — calling an LLM/API
  is an integration and is allowed). Packages describing applications outside
  their declared envelope MUST fail L0.
- **`scope`** (optional) declares `contracted` and `unscoped` surface lists.
  Regeneration and conformance target the contracted scope ONLY; unscoped
  surfaces MUST be inventoried in `interface/unscoped-surfaces.yaml` if the
  as-built application has them. A package without `scope` claims the whole
  application.
- **`versions`**: `spec` increments on any contract-layer change; `data`
  increments ONLY on data-contract change. See §10 for breaking-change rules.
- **`datastores`** (required when more than one store exists) names each
  store, its kind, and its schema provenance. Behavioral checks reference
  stores by these names (§7.3).
- **`rebuild`**: `cadence` and `mode`. `mode: plan-then-apply` is the only
  mode defined in v0.2; silent apply is not specified.
- **`testing`** declares the **testing contract** (§8). Builders MUST
  implement it; the gate depends on it.
- **`extraction`** records how the package was produced (`manual` or an
  extractor identifier) and when.

## 4. Intent (`intent.md`)

Prose, human-first. Required sections: Purpose; Users; Core jobs; What breaks
if it vanishes; **Known quirks**. Recommended: Out of scope.

Nothing load-bearing may live ONLY in prose. If an assertion must influence a
build or a gate, it MUST also exist in a machine-readable layer. (This rule
exists because prose loses to stack defaults: a route described as "public" in
prose was denied by a framework's default-deny posture in round-3 testing.
See §6 route auth exposure.)

**Known quirks** are as-built truths — behaviors that exist whether or not
anyone intended them — assigned stable identifiers (Q1, Q2, ...). Quirks are
CONTRACT: per Hyrum's Law, observable behavior accrues dependents, so a build
that "fixes" a quirk has made an unapproved breaking change. Fixing a quirk is
a contract change requiring the plan/apply workflow. Contracts and invariants
SHOULD reference quirk ids.

## 5. Data layer (`data/`) — the sacred layer

Code is disposable; data is not. Three rules are absolute:

1. **Builders MUST NOT create, alter, or drop schema** in any declared
   datastore. A build whose needs exceed the declared schema MUST fail its
   plan and demand a human-authored migration.
2. **Migrations are history, not state.** `data/migrations/` is ordered and
   append-only. When the source application has a real migration history
   (Flyway, Drizzle, Rails, ...), the extractor MUST carry it verbatim, in
   engine order, and the history itself is contract: a rebuild MUST NOT
   flatten it into a synthetic clean schema. Migration files MAY be native
   SQL or YAML-wrapped; each MUST be attributable to a store when multiple
   stores exist.
3. **Inferred schema is a claim, not a fact.** When schema lives outside the
   repository (vendor consoles, hidden DB functions), the extractor emits its
   best reconstruction with `status: unconfirmed` and explicit `UNKNOWN`s,
   and the confirmation queue (§11) prioritizes resolving them.

`entities.yaml` supports two shapes: a single top-level `entities:` map, or a
map of store-name → `{entities: ...}` for multi-store applications. Every
entity MUST carry `provenance` (§11). Fields declare `type` (free-form, with
`ref(<entity>)` for references and `UNKNOWN(...)` as a legal value),
optional `pk`, `nullable`, `default`, `unique`, and free-form `note`.
Entities MAY declare `unknowns:` — a list of things the extractor could not
determine. Database-side functions with behavioral contracts (e.g. an atomic
create with a hidden limit) are declared as `db_function` entries with a
prose `contract` and UNKNOWN parameters where applicable.

`classifications.yaml` (optional) maps `entity.field` to an org taxonomy:
class (pii.*, credential, ...), retention, residency, logging permissions.

## 6. Interface layer (`interface/`)

### 6.1 Programmatic surface — `api.openapi.yaml`
OpenAPI 3.x, with these format rules:

- **Route auth exposure MUST be machine-readable.** Every operation carries
  `x-auth: none | session | token | public-cors`. Adjectives in description
  text do not count. (v0.2 addition; forced by the Spring default-deny
  finding.) `public-cors` additionally asserts CORS `*` semantics including a
  204 OPTIONS preflight.
- Response *shape* contracts use standard OpenAPI schemas; the conformance
  gate enforces the JSON-Schema subset: `type`, `required`, `properties`,
  `items`, `minItems`, `maxItems`, and null-permitting type arrays.
- **Error-body shape SHOULD be contracted** where dependents may parse it.
  Differential testing shows independent implementations diverge on error
  bodies almost immediately; an uncontracted error shape is a known
  equivalence gap, not an oversight to hide.
- Locale-dependent message TEXT MUST NOT be contract; gate on status codes
  and shapes.

### 6.2 Human surface — `surfaces.yaml`
Declares surfaces (`id`, `route`, `purpose`, `auth`, `pinned` element list)
and navigation. Pinning is at the level of what users experience — fields,
actions, flows — not styling. Interface contracts are the weakest-verified
layer in current practice; packages SHOULD carry honest (low) confidence
provenance here rather than fabricated precision.

### 6.3 `unscoped-surfaces.yaml`
Inventory of as-built surfaces outside the contracted scope, with a
`reason_note`. Builders MUST NOT be gated on these and SHOULD NOT build them.

## 7. Behavior layer (`behavior/`) — the gate

Three tiers, composed from existing languages (the format deliberately
invents no new behavioral language):

### 7.1 Invariants (`invariants.yaml`)
Top-level `invariants:` list. Each entry: `id` (stable, INV-###),
`statement` (prose), `provenance` (REQUIRED), optional `note`, and an
optional machine `check:` — a probe with `request` and `expect` in the same
grammar as golden cases (§7.3). Invariants without checks are legal but count
against coverage (§9). A top-level `known_nonguarantees:` list declares
behaviors the application observably does NOT promise (races, resets that
never happen, content that varies with upstream latency); these prevent
gates and builders from inventing guarantees.

### 7.2 Scenarios (`scenarios/*.feature`)
Gherkin. In v0.2 scenarios are normative documentation and coverage debt:
conformance runners are not yet required to execute them. Experience note:
builders demonstrably read scenarios and self-verify against them even when
runners cannot — write them as if executable.

### 7.3 Golden cases (`golden/*.cases.yaml`)
Each file is a list of cases:

```yaml
- name: <unique human name>
  setup: { ... }                       # optional, documentary
  request:
    method: GET|POST|PUT|PATCH|DELETE
    path: /api/...                     # may embed $fixture.* tokens
    headers: { ... }                   # may embed $fixture.* tokens
    body: { ... } | "raw string"
  expect:
    status: <int>
    body_contains: { subset match }        # optional
    body_not_contains: [ "needle", ... ]   # optional; raw-substring absence
    body_schema: { inline JSON-Schema subset }        # optional
    body_schema_ref: "interface/api.openapi.yaml#/paths/~1..."  # optional
    db_checks:                             # optional, executable side effects
      - name: <label>
        store: <datastore name>            # required when >1 store declared
        query: "select ..."                # scalar-returning
        equals: "<string>"                 # post-state equality
        # or: delta: <number>              # (post - pre) across the request
  mutates_fixtures: true                   # REQUIRED if the case changes seeded state
  provenance: { kind: declared|inferred|observed, ... }
```

`$fixture.<path>` tokens resolve against the verification fixtures (§8.2);
a case with unresolved tokens is SKIPPED, not failed. Cases marked
`mutates_fixtures: true` (v0.2 addition) require a fresh substrate; runners
SHOULD refuse to execute them against dirty state. Golden cases with
`kind: observed` provenance are promoted production traces — the
Hyrum's-Law defense — and are the preferred long-term source of goldens.

**db_check portability (normative).** A `db_check` query's result MUST NOT
depend on how a particular database or driver renders a value — most
commonly booleans (`t` vs `true` vs `1`) but also NULL, timestamps, and
numeric formatting. A query returning a raw boolean is non-conformant because
its `equals` value silently encodes one engine's representation. Authors MUST
project to explicit, engine-independent string literals — e.g.
`select case when <cond> then 'OK' else 'VIOLATION' end` — so the assertion
means the same thing on every conforming datastore. (This rule was added
after a greenfield package's `equals: "t"` boolean check passed under psql
but failed against a build whose driver rendered the same boolean as `true`;
the defect was in the contract, not the build.)

## 8. Testing contract

Vendor-coupled concerns (OAuth identity, hosted auth) make behavior
unverifiable in test environments. The manifest's `testing:` block declares
substitutions the builder MUST implement, gated behind explicit opt-in:

### 8.1 `auth_mode: header-principal`
When the environment variable `TEST_AUTH=1`, the application accepts an
`x-test-principal: <email>` request header as an authenticated session for
that email. Unknown principals materialize exactly as a first sign-in would.
Extensions MAY be declared for app-specific auth-adjacent state (e.g. a
consent gate: `x-test-consent: none` materializes/uses an unconsented
principal so the gate itself is probeable). This mode MUST be inert unless
`TEST_AUTH=1` is explicitly set, and MUST NOT ship enabled.

### 8.2 Fixtures (`fixtures.example.yaml`)
Template for `fixtures.yaml` used at verification time:
`fixture:` (named values — principals, seeded row identifiers, secret
material for probes) and `db:` (datastore adapters). `db:` is either a
single adapter (`mode: command | psycopg` with `command:` template or `dsn:`)
or a map of store-name → adapter matching `manifest.datastores`.

## 9. Conformance levels and metrics

- **L0 Valid** — package parses; required files present; every contract
  assertion carries provenance; envelope declared.
- **L1 Coherent** — cross-references resolve: golden/probe paths exist in the
  OpenAPI surface (query strings ignored), `ref()` targets exist, migrations
  well-formed, schema refs resolvable.
- **L2 Verified** — behavioral gates pass against a RUNNING build: goldens,
  invariant probes, db_checks.
- **L3 UI-Verified** — interface contract gates pass against a RUNNING build
  in a real browser: screen structure and anchors, design-token bindings and
  palette conformance, verbatim copy, journey-shape flows, accessibility
  rules. Requires a `ui/` layer; packages without one report not-applicable.
  Normative definition: SPEC-UI.md.
- **L4 Governed** — build satisfies policy bindings and emits attestation:
  SBOM, signed build provenance, and a record of ambient context present at
  build time. (Context-at-build-time is attestation-relevant: build agents
  observably absorb ambient instructions; what was present must be
  recordable.) L4 is specified at this level of detail only in v0.2.

**Metrics.** Reports MUST include:
- **fidelity** = pass / (pass + fail) over executed gates;
- **l2_fidelity** = the same ratio over executed L2 gates only (the number
  that describes the BUILD rather than the package);
- **L2 coverage** = executed L2 gates / declared L2 gates.

Fidelity without coverage is not a meaningful claim; publications of results
MUST state both. Neither metric measures the package against the full
behavior of the source application; that requires differential testing
against the original, which is the only way to detect contract GAPS.

## 10. Versioning and breaking changes

- Data-contract changes are ALWAYS breaking: bump `versions.data`, require a
  human-authored migration and plan approval. Never automated.
- Modifying or removing any invariant, golden, scenario, or interface
  contract is breaking. ADDING behavioral coverage is non-breaking.
- Quirk fixes are contract changes (breaking) even when they are "obviously"
  bug fixes.
- Intent prose, hints, and `replaceable: true` integration swaps are
  non-breaking and eligible for automated rebuild cadence.
- Policy changes are non-breaking for the format, but the plan MUST surface
  behavioral consequences (e.g. an org SSO policy colliding with as-built
  vendor OAuth is a breaking interface change and requires approval).

## 11. Provenance model

Every contract assertion carries provenance:

```yaml
provenance:
  kind: declared | inferred | observed
  confidence: 0.0-1.0        # required for inferred
  evidence: ["path:lines", "the app's own test suite: ...", ...]
  note: "..."
```

- **declared** — a human stated or confirmed it.
- **inferred** — an extractor's judgment from artifacts. The target
  application's OWN test suite is citable evidence and typically warrants
  the highest inferred confidence.
- **observed** — derived from production traffic/traces.

`UNKNOWN` is a legal value anywhere a fact could not be determined; an
extractor that guesses instead of declaring UNKNOWN is non-conformant.

`provenance.lock` is the generated ledger: counts by kind, and a
**confirmation queue** ordered by how much behavior/security rides on each
unconfirmed assertion. Two epistemic rules govern confirmation:

1. Regeneration conformance can NEVER confirm an inferred assertion — a
   build matching the package proves consistency with the package, not that
   the package matches the original. Confirmation requires probing the
   source system (or a human who knows).
2. When a human confirms an assertion, its kind flips to `declared` and the
   event is appended to `history`.

## 12. Extractor obligations (normative summary)

An extractor MUST: emit provenance on every assertion; prefer `UNKNOWN` to
guessing; carry real migration histories verbatim; record as-built quirks as
contract with stable ids; declare scope honestly and inventory unscoped
surfaces; mine the target's own test suite as evidence where present;
populate the confirmation queue ordered by risk; and never silently
normalize as-built behavior toward intended behavior (contract-as-built vs
contract-as-intended is the human's decision, surfaced — not the
extractor's, hidden).

## 13. Builder obligations (normative summary)

A builder MUST: treat contracts as binding and hints as disposable; preserve
quirks; never create/alter/drop schema in declared datastores; implement the
testing contract exactly as declared (inert without explicit opt-in); build
only the contracted scope; not consult the original application's source;
and treat the conformance gate as the definition of done — including saving
the FIRST verification report before any fixes, so iteration cost is
measurable. A builder SHOULD surface disagreements between the package's
assumptions and its own implementation judgment (e.g. an assumed status
code) rather than silently conforming; such disagreements are confirmation-
queue material.

## 14. Security considerations

Secret VALUES never appear in packages — references only. The testing
contract is an authentication bypass by design and MUST be inert outside
explicit test opt-in. Regeneration cadence is a moving-target defense
(application-layer persistence dies at rebuild) but each rebuild is also a
fresh supply-chain event: L4 attestation (SBOM, signed provenance,
build-time context record) exists to make that trade auditable. Policy
deny-lists in `build/constraints.yaml` are the injection point for
vulnerability intelligence at generation time.
