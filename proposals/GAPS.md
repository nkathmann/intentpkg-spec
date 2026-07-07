# Gap Register

Known coverage gaps in the base format, each with a design sketch, its
proposal status, and an honest priority. The envelope (`internal-web-app/v1`)
is deliberately narrow; this register is the roadmap for widening it without
pretending v0.x already covers everything.

| # | Gap | Status | Sketch |
|---|-----|--------|--------|
| 1 | Async: events, jobs, outbound calls, eventual consistency | **Proposal 0002**; job triggering + reset landed in the testing contract | channels, `eventually`, sinks, TEST_HOOKS job triggering |
| 2 | Multi-service composition | **Proposal 0001** | system packages, bindings, pairwise SL2 |
| 3 | Authorization matrices | sketch below | declarative roles×actions grid, expanded to probes |
| 4 | State machines / workflow | sketch below | declared transitions; generated allow/deny probes |
| 5 | Derived data (caches, indexes, embeddings) | sketch below | derived-store declarations with staleness budgets |
| 6 | Files / multipart | sketch below | multipart request grammar + content-hash checks |
| 7 | Non-functional budgets (latency, availability) | sketch below | measured budgets, L4-adjacent (attestation-attached) |
| 8 | Trace promotion (observed goldens at scale) | tooling gap | format ready (`kind: observed`); pipeline unbuilt |
| 9 | Realtime (websockets, SSE) | unscoped | out of envelope until demand; no sketch yet |
| 10 | Non-HTTP RPC surfaces (gRPC) | unscoped | blocks 0001 `expects` for gRPC meshes |
| 11 | Package identity & integrity | rule practiced; hash unbuilt | content-hash in every report; revision rule enforced by runner |
| 12 | Verification-adapter trust (TCB) | rule shipped; probe unbuilt | engine canary in L2; adapter attestation at L4 |
| 13 | Interactivity coverage metric | tooling gap | % of interactive components exercised by ≥1 flow, reported per run |
| 14 | Fixture completeness | rule practiced; lint unbuilt | every seed property a gate asserts must be fixture-declared |
| 15 | Report of record | README text; SPEC sentence pending | JSON report governs; prose never overrides; waivers are package changes |
| 16 | Schema extension escape valve | decision pending (v0.4) | sanctioned `x-` prefix vs. strict-everywhere |
| 17 | Geometry assertions | runner gap | declared region geometry parses at L0/L1 but skips at L3 (27 skips/run) |

## 3. Authorization matrices
`interface/authz.yaml`: `roles`, `resources`, and a `grid` of
role×resource→allowed actions. The gate EXPANDS the grid mechanically: one
probe per cell (allowed → expect success-class; absent → expect 403/404 per
the app's declared denial idiom — see applikon Q1 for why the idiom is
per-app contract). Testing contract gains `x-test-roles`. Economics: a 6×10
grid is 60 generated probes from 20 lines of declaration — the scaling
answer for RBAC-heavy apps. Risk to design around: grids drift from code;
extraction must mine route guards, not trust documentation.

## 4. State machines
`behavior/state-machines.yaml`: per entity-field, `states`, `transitions`
(from→to, optional guard prose, optional trigger route), and the explicit
degenerate declaration `unrestricted: true` (applikon Q4 — the ABSENCE of a
machine is contract too). Gate generates: each declared transition probed
via its trigger; each UNdeclared transition probed and expected to fail.
Fixture cost is the hard part: each from-state needs a seeded row.

## 5. Derived data
`data/derived.yaml`: stores/fields whose content is recomputable from a
source of truth (caches, search indexes, vector embeddings — unicon's
`embedding` column note, made first-class). Declares: `source`, `rebuild`
(how it regenerates), `staleness_budget` (an `eventually` window on
consistency with source). Builders MAY drop and rebuild derived data
freely; the sacred-layer rules apply only to source-of-truth data. This
sharpens §5's "data is sacred" into "TRUTH is sacred; derivations are cattle."

## 6. Files / multipart
Request grammar gains `multipart:` bodies with file fixtures
(`$fixture.files.<name>` resolving to harness-provided test files);
db/response checks gain `content_hash` assertions. Unblocks the CV-class
endpoints scoped out of applikon. Runner: multipart encoding, a file
fixtures directory. Small, well-understood; scheduled behind demand.

## 7. Non-functional budgets
`budgets.yaml`: p95 latency per surface, error-rate ceilings, availability
targets. These are MEASURED against runs, not pass/fail gated in L2 (a
laptop verify run proving p95 is meaningless); they attach to L4 attestation
where the measurement environment is declared. Deliberately last: pretending
performance is a functional gate produces theater.

## 8. Trace promotion
The format already has the slot (`provenance.kind: observed`, golden cases,
promotion history in provenance.lock). Missing is the pipeline: capture
production traffic, cluster it, draft goldens, human-confirm, promote.
This is the economics answer for large applications — the biggest apps have
the most traffic and therefore the cheapest path to coverage — and it is
the extractor product's second act, not a spec change.

## 11. Package identity & integrity
Found the expensive way: a builder ran against a stale package tarball that
carried the same format identifier as its corrected successor — two
materially different contracts, indistinguishable by any declared field.
Sketch: (a) every runner report embeds a canonical content hash of the
package tree (the build-hash discipline from the baseline/blessing protocol,
applied to the package itself); (b) revision rule — any normative change
bumps `versions.spec`, and the runner warns when the provenance history's
latest entry postdates the manifest version. The revision rule is practiced
(flagship package v0.3.2→v0.3.5); the hash is unbuilt. Terminates in L4:
signed provenance for builds implies signed provenance for packages.

## 12. Verification-adapter trust
Found by a cross-model build: a builder on the wrong substrate made its
fixtures `db.command` adapter translate the package's PostgreSQL queries
into its dialect in flight — every green DB gate was testing rewritten
evidence. The adapter is part of the trusted computing base and needs its
own integrity story. Shipped: normative transparency rule (constraints
`verification_adapter: transparency: required`; builder-skill honesty rule).
Unbuilt: the L2 engine canary — run `select version()` through the adapter
at verify start and match the declared engine; a shim then has to forge an
engine banner to survive, which is no longer misjudgment but forgery.
Long-term: adapter attestation belongs in L4.

## 13. Interactivity coverage metric
Found by the fidelity-1.0-unusable build: rows and tabs rendered but did
nothing, in exactly the region no flow reached. Flows now gate those paths,
but the class-level fix is a visibility number: the runner should report
the fraction of declared interactive components exercised by at least one
flow step, alongside fidelity and coverage. Not a pass/fail gate — a number
that makes "nothing clicks here" glaring before a human does the clicking.

## 14. Fixture completeness
Twice, gate expectations depended on seed properties that only the reference
harness happened to provide (asserted ticket subjects; an unrouted seed).
Rule, now practiced: every seed property a gate asserts must be
fixture-declared, and flows assert fixture references, not literals.
Unbuilt: an L1 lint flagging literal strings in flow text assertions as
suspects (a `contains_text` that is not a `$fixture.` reference or a copy
key deserves a warning).

## 15. Report of record
A builder delivered red gates relabeled "expected/acceptable" in prose.
The countermeasure is structural, not exhortative: the JSON report is the
artifact of record; prose never overrides it; a failing gate stays failed;
waiving a gate is a package change only the package owner can make; and any
consuming pipeline gates on `summary.level` and `schema_validated`, never on
a README's characterization. One sentence of SPEC.md §9 text pending.

## 16. Schema extension escape valve
The schemas enforce `additionalProperties: false` everywhere — which is what
makes misspelled keys impossible, and also what makes every experimental
field a schema change. The standard resolution is a sanctioned `x-` prefix
(OpenAPI's move): experiments get a home that can never be confused with a
typo. Costs one governance decision and touches every schema; deferred to
v0.4 so it happens once, deliberately.

## Closed this cycle (v0.3.1 → v0.3.5)
For the record, promotions that moved from this register's spirit into the
gate, each dated in the flagship package's provenance.lock: interactivity
flows with negative assertions (dead-UI build); L1 job-reference and
db-table-existence checks (two silent-key incidents); fixture-pinned
assertion data (twice); database engine pinning plus adapter transparency
(translating-adapter build); loud failure on missing role mappings and
honest `schema_validated` reporting (quiet-degradation hunts). The pattern
across all of them: deviation finds the softest unguarded spot; the spot
becomes declared and gated; the class dies. This register exists so the
next spot is on a list before a build finds it.
