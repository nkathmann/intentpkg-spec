# Proposal 0001 — System Composition (intentpkg-system)

Status: DRAFT proposal for v0.4 (or sibling spec). Additive; no changes to
member package semantics.

## Problem

Large applications are meshes of services. The base format describes one
application inside the `internal-web-app/v1` envelope; it has no grammar for
"these N packages together deliver one product," no way to verify that
service A's assumptions about service B hold, no async/event topology, and no
blast-radius computation when a provider contract changes.

## Model

A **system package** composes member packages. Members remain complete,
independently regenerable intent packages; the system package owns only what
exists BETWEEN them.

```
acme-orders.intent-system/
├── system.yaml              # members, bindings, rebuild orchestration
├── intent.md                # system-level purpose, users, what-breaks
├── channels/
│   └── channels.yaml        # async topology: events, producers, consumers
├── data/
│   └── ownership.yaml       # entity-domain ownership across members
├── behavior/
│   ├── flows/*.feature      # end-to-end scenarios spanning members
│   └── golden/*.cases.yaml  # cross-service goldens (store-qualified db_checks)
├── policy/                  # system-level org policy (injected)
└── provenance.lock
```

Recursion is legal: a system package may appear as a member of a larger
system (systems of systems), enabling domain-level composition.

## 1. Members and bindings (`system.yaml`)

```yaml
format: intentpkg-system/v0.1
system:
  id: acme-orders
  title: "Order intake, pricing, and notification"
members:
  intake:   { package: ../intake.intent,   pin: { spec: 4, data: 2 } }
  pricing:  { package: ../pricing.intent,  pin: { spec: 7, data: 3 } }
  notifier: { package: ../notifier.intent, pin: { spec: 2, data: 1 } }
bindings:
  # consumer-side integration  ->  provider-side interface
  - id: B-001
    consumer: { member: intake, integration: pricing-api }
    provider: { member: pricing, surface: api }
    provenance: { kind: inferred, confidence: 0.95,
                  evidence: ["intake: src/pricing-client.ts"] }
  - id: B-002
    consumer: { member: notifier, channel_subscription: order-events }
    provider: { member: intake, channel: order-events }
    provenance: { kind: declared }
rebuild:
  mode: plan-then-apply
  independence: >
    Members rebuild on independent cadences PROVIDED all bindings that name
    them still verify (SL2). A rebuild that breaks a binding fails its plan.
```

## 2. Consumer expectations (member-package extension, additive)

To make bindings *verifiable* rather than aspirational, a consumer package's
`integrations/integrations.yaml` entry MAY carry an `expects:` block — the
consumer-driven contract, expressed in the existing golden-case grammar:

```yaml
# inside intake.intent/integrations/integrations.yaml
- id: pricing-api
  kind: internal-service
  replaceable: false
  expects:                      # what THIS consumer actually relies on
    - name: quote for a sku returns price and currency
      request: { method: POST, path: /api/quotes, body: { sku: "probe-sku", qty: 2 } }
      expect:
        status: 200
        body_schema:
          type: object
          required: [price, currency]
          properties: { price: { type: integer }, currency: { type: string } }
    - name: unknown sku is 404 not 200-with-null
      request: { method: POST, path: /api/quotes, body: { sku: "zzz-none", qty: 1 } }
      expect: { status: 404 }
```

`expects` is deliberately a SUBSET: the consumer contracts only what it uses.
Providers stay free to evolve everything no consumer has claimed — this is
the Postel/Pact discipline that lets a mesh evolve without lockstep releases.

## 3. Channels (`channels/channels.yaml`) — async topology

Events become first-class. Message shapes reuse the JSON-Schema subset;
delivery semantics are declared, not implied. (This section is also the
base format's async gap fix; single-service packages MAY declare channels.)

```yaml
channels:
  - id: order-events
    kind: topic                    # topic | queue
    message_schema:
      type: object
      required: [order_id, status, total]
      properties:
        order_id: { type: string }
        status:   { enum: [CREATED, PRICED, CANCELLED] }
        total:    { type: integer }
    producers: [intake]
    consumers: [notifier]
    delivery: { semantics: at-least-once, ordering: per-key, key: order_id }
    known_nonguarantees:
      - "consumers MUST tolerate duplicates (at-least-once)"
```

Gate grammar gains `channel_checks` (system-level goldens): publish/expect on
channels, and eventual assertions with an explicit deadline:

```yaml
- name: created order eventually notifies
  request: { method: POST, path: intake:/api/orders, body: { sku: "probe-sku", qty: 1 } }
  expect:
    status: 201
    channel_checks:
      - channel: order-events
        eventually: { within: 10s }
        message_contains: { status: CREATED }
    db_checks:
      - store: notifier.primary          # member-qualified store names
        eventually: { within: 15s }
        query: "select count(*) from notifications where kind = 'order-created'"
        delta: 1
```

`eventually.within` makes eventual consistency a stated contract instead of a
flaky test: the gate polls to the deadline; the deadline is part of the
package and reviewable like any contract value.

## 4. Data ownership (`data/ownership.yaml`)

Each entity domain is owned by exactly one member; all other access crosses
an interface or channel. Shared databases are detectable and must be either
refactored or DECLARED as a system quirk (contract-as-built applies at
system scale):

```yaml
ownership:
  orders:        { owner: intake }
  prices:        { owner: pricing }
  notifications: { owner: notifier }
violations_declared: []   # as-built shared-store access, if any, with quirk ids
```

## 5. System conformance levels

- **SL0 Valid** — system package parses; every member passes L0; pins match
  member manifests.
- **SL1 Coherent** — binding graph resolves: every binding's consumer and
  provider exist; every `expects` path exists in the provider's OpenAPI (the
  L1 path check, cross-package); channel producers/consumers are members;
  ownership map is conflict-free and total over member entities.
- **SL2 Pairwise-verified** — for each binding, the consumer's `expects`
  execute as gates against the PROVIDER's build alone. No full-mesh
  deployment required; verification cost scales with bindings, not with the
  product of members. A provider build is not done until it passes its own
  L2 AND every consumer's expects.
- **SL3 Flow-verified & governed** — end-to-end flows and channel_checks pass
  against a composed deployment; attestation aggregates across members
  (SBOMs, build provenance, build-time context) into one system record.

## 6. Change management and blast radius

The binding graph makes impact computable. A provider contract change is
breaking IFF some binding's `expects` references the changed element; the
plan step MUST enumerate affected consumers by binding id ("changing
/api/quotes response shape breaks B-001: intake"). Consumer expectation
changes are never breaking for providers (a consumer asking for more may
simply fail SL2 until the provider provides it). Channel message-schema
changes are breaking for all declared consumers of the channel. Data
ownership transfers are always breaking and require a human-authored plan.

## 7. Extraction at system scale

A system extractor: extracts each member; infers bindings from observed
cross-service calls (client code, service discovery config, traffic) with
provenance and evidence; infers channels from queue/topic client usage;
drafts `expects` blocks from the CONSUMER'S OWN usage sites (the calls it
actually makes and the fields it actually reads — field-level usage is the
honest basis for a consumer contract); and populates ownership from each
member's data contracts, declaring violations rather than hiding them.

## 8. Open questions

1. Version-pin semantics: exact pins vs compatible ranges; interaction with
   independent rebuild cadences.
2. `expects` against non-HTTP providers (channel expectations partially
   cover this; RPC/gRPC surfaces do not exist in the base format yet).
3. Whether system packages may inject policy into members or only add
   system-level policy (current position: members' policy/ remains the org
   plane's; system policy/ is additive).
4. Composed-deployment description for SL3 (deliberately out of scope: the
   format describes contracts, not orchestration — Compose/K8s manifests are
   build artifacts).
