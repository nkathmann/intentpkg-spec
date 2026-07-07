# Runner conformance harness

A reference-conformant mock build of `examples/helpdesk.intent` (Python
stdlib + SQLite, reseeds on boot) used to test the runners themselves.
`VIOLATIONS=1` plants six deliberate contract breaches (missing anchor,
swapped focus order, reworded copy, off-palette color, forbidden portal
accent, injected dialog).

Two checks define a working UI runner (run from repo root):

    # 1. clean build -> everything must pass
    TEST_AUTH=1 TEST_HOOKS=1 PORT=8787 python3 tools/harness/app.py &
    python3 tools/intentpkg_ui_runner.py verify examples/helpdesk.intent \
      --base-url http://127.0.0.1:8787 --fixtures tools/harness/fixtures.harness.yaml

    # 2. violations build -> all six plants must fail, nothing else may
    VIOLATIONS=1 TEST_AUTH=1 TEST_HOOKS=1 PORT=8788 python3 tools/harness/app.py &
    python3 tools/intentpkg_ui_runner.py verify examples/helpdesk.intent \
      --base-url http://127.0.0.1:8788 --fixtures tools/harness/fixtures.harness.yaml

`helpdesk.db` is created at boot; never commit it.

Scope disclosure: this harness runs on SQLite and does NOT apply the
package's PostgreSQL migration — it is a UI-gate (L3) conformance harness,
deliberately NOT a data-layer-conformant build. It must never be cited as an
L2-conformant reference. (The engine pin in build/constraints.yaml, v0.3.4,
exists precisely because a build made this same substitution silently.)
