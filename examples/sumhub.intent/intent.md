# Sumhub — Intent

## Purpose
Sumhub accepts numeric values posted by multiple upstream systems and exposes
their running total. It exists so downstream consumers read ONE agreed number
instead of each re-aggregating the sources themselves.

## Users
- **Producer systems** (machine): POST values with a shared intake token.
- **Consumer systems** (machine): GET the current sum with the same token.
- No human UI; this is an API-only service.

## Core jobs
1. POST /api/values — record {source, value}; every accepted value counts.
2. GET /api/sum — return the current total and count, derived from storage
   (never a cached counter that can drift).

## What breaks if it vanishes
Downstream consumers of the total; producers buffer or drop.

## Known quirks
- (none — greenfield example; see known_nonguarantees in invariants for the
  behaviors this app deliberately does NOT promise)
