# intentpkg — Intent Package Format (working name)

**Status: v0.2-draft. Working name — the format will be renamed before 1.0.**

An intent package is the durable, regenerable specification of an application:
business intent, data contracts, interface contracts, executable behavioral
contracts, integrations, and org policy bindings — with per-assertion
provenance. The thesis: **the spec is the application; the code is a build
artifact**, rebuilt on a cadence from the package under current dependencies
and policy, and trusted because it passes the package's gates — not because
the generator is trusted.

Two kinds of tools implement this format:

- **Extractors** analyze an existing application (source, schema, traffic) and
  emit a package. Their obligations: honest provenance, `UNKNOWN` over
  guessing, evidence pointers, quirks recorded as contract.
- **Builders** read a package and produce a running application. Their
  obligations: contracts are binding, hints are disposable, quirks are
  preserved not fixed, data stores are never touched, and the build isn't done
  until the conformance gate passes.

## Repository layout
```
SPEC.md              normative specification (RFC 2119 language)
schemas/             JSON Schemas for every package file (validation targets
                     for both extractors and builders)
examples/            canonical example packages (start with sumhub.intent —
                     a complete minimal package, ~15 files)
proposals/           numbered design proposals for spec evolution
                     (0001: system composition; 0002: async & temporal
                     contracts) plus GAPS.md, the honest coverage-gap
                     register with design sketches
```

## Empirical grounding
The format has been exercised by hand-extracting three real AI-generated
applications (Next.js/Supabase, Next.js dual-store SQLite+Postgres, and
Java 21/Spring Boot) and regenerating each from its package alone, verified by
an executable conformance gate (fidelity 1.0 in all captured reports; L2 probe
coverage 0.76–0.87). Format changes in v0.2-draft were forced by those
experiments, not designed in the abstract. See the evidence ledger in the
companion repository.

## License
Apache-2.0 (spec text and schemas).
