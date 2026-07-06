# Proposal 0002 — Async & Temporal Contracts (base format)

Status: DRAFT for v0.3. Additive to single-service packages. Aligns with
0001's channel grammar so system composition inherits it unchanged.

## Problem

The v0.2 gate vocabulary is request → response → db_check: synchronous,
inbound, immediate. Real applications also (a) consume and produce events,
(b) run scheduled jobs, (c) make outbound HTTP calls (webhooks, third-party
notifications), and (d) settle state *eventually* rather than within the
request. Today all of that is prose (see unicon INV-008: a fire-and-forget
analytics write that had to be left unprobed with an apology). This proposal
gives each of those a grammar and a verification mechanism.

## 1. Temporal grammar: `eventually` (and bounded absence)

Any `db_checks`, `channel_checks`, or `outbound_checks` entry MAY carry:

```yaml
eventually: { within: 10s, poll: 500ms }   # poll defaults to within/20
```

Semantics: the runner polls until the assertion holds or the deadline
passes; the deadline is contract — reviewable, versioned, and honest about
the app's consistency window. Immediate checks (no `eventually`) keep v0.2
semantics.

Bounded absence is the dual and MUST be explicit about its cost:

```yaml
never: { within: 5s }    # assertion must hold at EVERY poll for the window
```

`never` checks consume their full window by construction; packages SHOULD
use them sparingly (dead-letter emptiness, "no notification sent on
validation failure").

## 2. Channels (`interface/channels.yaml`)

A service declares what it **produces** (interface) and what it **consumes**
(integration-like), symmetric with proposal 0001:

```yaml
produces:
  - id: order-events
    kind: topic
    message_schema:
      type: object
      required: [order_id, status]
      properties: { order_id: {type: string}, status: {enum: [CREATED, CANCELLED]} }
    delivery: { semantics: at-least-once, ordering: per-key, key: order_id }
consumes:
  - id: payment-events
    kind: topic
    expects_schema:              # the subset of the message THIS consumer reads
      type: object
      required: [order_id, outcome]
    on_duplicate: idempotent     # declared consumer discipline (at-least-once world)
    on_malformed: dead-letter | drop | halt
```

`known_nonguarantees` patterns apply ("consumers MUST tolerate duplicates").
Producers' message schemas are breaking-change surfaces exactly like OpenAPI
response schemas (§10 of SPEC).

## 3. Gate actions beyond HTTP: `publish`

Golden cases and invariant checks gain an alternative to `request:` —
publishing a message to drive a CONSUMER's contract:

```yaml
- name: payment success marks the order paid
  publish:
    channel: payment-events
    message: { order_id: "$fixture.order.id", outcome: "SUCCESS" }
  expect:
    db_checks:
      - query: "select status from orders where id = $fixture.order.id"
        equals: "PAID"
        eventually: { within: 10s }
```

Channel transport is fixture-configured, adapter-style (same philosophy as
db adapters — the format does not pick a broker):

```yaml
# fixtures.yaml
channels:
  payment-events:
    mode: command
    publish_command: "redis-cli lpush payments {message}"   # or psql insert, kafka-console-producer, ...
```

## 4. Outbound calls: sinks and `outbound_checks`

The app as HTTP *caller* becomes gateable by pointing its outbound
destinations at a capture sink during verification. The integration entry
declares the env indirection; fixtures bind it to a sink the runner provides:

```yaml
# integrations/integrations.yaml
- id: slack-notify
  kind: outbound-webhook
  secret_refs: [SLACK_WEBHOOK_URL]     # MUST be env-indirected — this is what makes capture possible
  replaceable: true

# fixtures.yaml
sinks:
  slack-notify: { bind_env: SLACK_WEBHOOK_URL }   # runner serves a sink and injects its URL

# a golden case
- name: order creation notifies slack exactly once
  request: { method: POST, path: /api/orders, headers: {...}, body: {...} }
  expect:
    status: 201
    outbound_checks:
      - sink: slack-notify
        count: 1
        eventually: { within: 5s }
        request_contains: { method: POST, body_contains: { text_present: true } }
```

Format rule (normative): outbound destinations MUST be configuration, never
literals — both because policy injection requires it and because an
unverifiable outbound call is an unverifiable contract.

## 5. Scheduled jobs (`behavior/jobs.yaml`)

```yaml
jobs:
  - id: nightly-rollup
    schedule: "0 2 * * *"
    provenance: { kind: inferred, confidence: 0.9, evidence: ["src/cron.ts:12"] }
    semantics:
      overlap: forbid            # forbid | allow | queue
      missed_runs: skip          # skip | catch-up
      idempotent: true           # re-running MUST be safe iff true
    effect:                      # the job's contract, in gate grammar
      db_checks:
        - query: "select count(*) from rollups where day = current_date"
          equals: "1"
```

### Test-time triggering (testing-contract extension)
Waiting for cron is not verification. When `TEST_HOOKS=1`, the build MUST
expose `POST /__test/jobs/{id}/run`, executing the job synchronously and
returning 200 on completion. Like TEST_AUTH, this surface MUST be inert
unless explicitly enabled and MUST NOT ship enabled. Job gates then read:

```yaml
- name: rollup is idempotent
  request: { method: POST, path: /__test/jobs/nightly-rollup/run }
  then:    { method: POST, path: /__test/jobs/nightly-rollup/run }   # run twice
  expect:
    status: 200
    db_checks: [ { query: "select count(*) from rollups where day = current_date", equals: "1" } ]
```

(`then:` — a minimal two-step sequence affordance for idempotency probes
only; full sequences remain scenario-runner territory.)

## 6. Conformance and metrics impact

New check kinds count in L2 coverage like any other. Runners implementing
this proposal add: a poller (eventually/never), an embedded capture sink,
channel adapters (command mode), and TEST_HOOKS awareness. Packages using
these features against a v0.2 runner see the gates SKIP with reason —
additive degradation, no breakage.

## 7. Open questions

1. Clock control for time-dependent LOGIC (not schedules): a TEST_CLOCK
   contract is deliberately deferred — high value, high implementation burden
   on builders.
2. Message-schema evolution rules (channel versioning) — likely mirrors
   OpenAPI breaking-change rules; needs a worked example first.
3. Whether `never` belongs in v0.3 or should wait for demand.
