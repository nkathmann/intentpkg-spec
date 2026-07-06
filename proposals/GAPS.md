# Gap Register

Known coverage gaps in the base format, each with a design sketch, its
proposal status, and an honest priority. The envelope (`internal-web-app/v1`)
is deliberately narrow; this register is the roadmap for widening it without
pretending v0.x already covers everything.

| # | Gap | Status | Sketch |
|---|-----|--------|--------|
| 1 | Async: events, jobs, outbound calls, eventual consistency | **Proposal 0002** | channels, `eventually`, sinks, TEST_HOOKS job triggering |
| 2 | Multi-service composition | **Proposal 0001** | system packages, bindings, pairwise SL2 |
| 3 | Authorization matrices | sketch below | declarative roles×actions grid, expanded to probes |
| 4 | State machines / workflow | sketch below | declared transitions; generated allow/deny probes |
| 5 | Derived data (caches, indexes, embeddings) | sketch below | derived-store declarations with staleness budgets |
| 6 | Files / multipart | sketch below | multipart request grammar + content-hash checks |
| 7 | Non-functional budgets (latency, availability) | sketch below | measured budgets, L3-adjacent |
| 8 | Trace promotion (observed goldens at scale) | tooling gap | format ready (`kind: observed`); pipeline unbuilt |
| 9 | Realtime (websockets, SSE) | unscoped | out of envelope until demand; no sketch yet |
| 10 | Non-HTTP RPC surfaces (gRPC) | unscoped | blocks 0001 `expects` for gRPC meshes |

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
laptop verify run proving p95 is meaningless); they attach to L3 attestation
where the measurement environment is declared. Deliberately last: pretending
performance is a functional gate produces theater.

## 8. Trace promotion
The format already has the slot (`provenance.kind: observed`, golden cases,
promotion history in provenance.lock). Missing is the pipeline: capture
production traffic, cluster it, draft goldens, human-confirm, promote.
This is the economics answer for large applications — the biggest apps have
the most traffic and therefore the cheapest path to coverage — and it is
the extractor product's second act, not a spec change.
