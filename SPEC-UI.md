# intentpkg format v0.3 — UI Contract Layer

Status: Draft for implementation. Extends format v0.2. Additive; a valid v0.2 package without a `ui/` directory remains a valid v0.3 package (L3 reports `not-applicable`).

---

## 1. Problem

Regeneration works for behavior because behavior is specifiable: a golden case either passes or it doesn't. UI is different. Functional intent underdetermines the interface — the same declared behavior admits infinite renderings, and generators exploit that freedom on every build. Users experience this as an application that rearranges itself on a cadence. No amount of behavioral fidelity compensates for a login button that moves, a nav that reorders, or an error message that rewords itself every regeneration.

The UI layer therefore has to constrain more than intent. It constrains **identity**: which screens exist, what is on them, where regions sit, what things are called, what they look like at the token level, and how core journeys traverse them. The line the format draws:

**Structure, tokens, copy, and flows are intent. Pixels are build artifacts.**

A package that pins the first four gets builds that are stable where users perceive stability. A package that pins pixels has smuggled the artifact back into the spec and will fight its own regeneration cadence forever.

## 2. Design principles

1. **Anchors are the contract surface.** Every declared interactive element carries a stable `data-testid`. Anchors make every other UI gate targetable, and they force the generator to preserve the interaction surface because the gates fail otherwise.
2. **Substrate pinning does the heavy lifting.** The manifest declares the UI substrate (framework, component library, styling system, token binding mechanism). Gates verify residual drift; the substrate prevents most of it.
3. **Constraints, not coordinates.** Layout is asserted as regions, ordering, and bounded geometry ("nav is a left rail 220–280px wide"), never absolute pixel positions.
4. **Visual baselines are provenance-tracked artifacts with a human blessing protocol.** The runner never blesses. A build that passes L3.S/T/F is *conformant*; visual blessing is operational policy on top of conformance, not part of it.
5. **Everything declared is verifiable.** As with v0.2 invariants, prose without a probe cannot score.

## 3. Package additions

```
<package>.intent/
  ui/
    screens.yaml            # screen inventory, regions, components, anchors, states
    tokens.yaml             # design tokens + binding rules
    copy.yaml               # copy registry: verbatim strings bound to anchors
    flows/
      <name>.flow.yaml      # journey gates, Playwright-executable
    baselines/              # OPTIONAL — artifacts, not intent
      manifest.yaml         # baseline provenance
      <screen>.<viewport>.<state>.png
```

`manifest.yaml` (package root) gains:

```yaml
ui_substrate:
  framework: nextjs            # informative
  components: shadcn/ui        # NORMATIVE: generator must use this library
  styling: tailwind
  token_binding: css-variables # tokens.yaml values surface as CSS custom properties
  viewports:                   # every L3 gate runs per-viewport unless scoped
    - { name: desktop, width: 1440, height: 900 }
    - { name: mobile,  width: 390,  height: 844 }
ui_gates:
  visual: off                  # off | advisory | enforced (see §10)
```

`components:` is normative for the same reason database engine pinning is: it is the single largest determinant of build-to-build visual variance. Changing it is a spec change, versioned like any other.

## 4. The anchor contract

Anchor = the value of a `data-testid` attribute. Naming: kebab-case, hierarchical, `<screen>.<region>.<element>`:

```
dashboard.header.new-key-btn
dashboard.keys-table
dashboard.keys-table.row-actions.delete
auth.login.email-input
```

Rules:

- **A4.1** Every component declared in `screens.yaml` MUST render with its declared anchor.
- **A4.2** Anchors are append-only across spec revisions. Renaming or removing an anchor is a breaking change to the package (major version bump), because flows, gates, and any downstream tooling reference them.
- **A4.3** Anchors MUST be unique per rendered screen state.
- **A4.4** The regeneration prompt MUST include the anchor list verbatim (§12). An anchor is part of the application contract exactly as an API route is.
- **A4.5** Extraction assigns anchors. When extracting from an app that lacks them, the extractor proposes anchor names from the accessibility tree; they become binding on the first regeneration (the first rebuild is where they enter the code). Provenance for these is `extracted-proposed` until a build has passed L3.S, then `confirmed`.

## 5. `ui/screens.yaml`

The screen inventory is the structural spine: which screens exist, what regions compose them, which components live in which region, what states each screen has, and how they are reached.

```yaml
version: 0.3
screens:
  - id: dashboard
    route: /dashboard
    title: "API Keys"                    # exact document/page title — copy-bound
    auth: required                       # uses v0.2 test-auth convention
    regions:                             # ordered; order is asserted
      - id: header
        landmark: banner                 # ARIA landmark the region must map to
        geometry: { position: top, height: { min: 56, max: 96 } }
      - id: main
        landmark: main
      - id: nav
        landmark: navigation
        geometry: { position: left, width: { min: 220, max: 280 } }
        viewports: [desktop]             # region may be viewport-scoped
      - id: nav-drawer
        landmark: navigation
        viewports: [mobile]
        initially: hidden
        revealed_by: dashboard.header.menu-btn
    components:
      - anchor: dashboard.header.new-key-btn
        region: header
        role: button
        copy: cta.new-key                # binds label to copy registry
      - anchor: dashboard.keys-table
        region: main
        role: table
        columns: [name, key, usage, created, actions]   # order asserted
      - anchor: dashboard.keys-table.empty
        region: main
        state: empty                     # only asserted in the empty state
        copy: empty.keys-table
    states:
      - id: default
        fixture: seeded                  # fixtures.yaml profile that induces it
      - id: empty
        fixture: empty-tenant
      - id: error
        fixture: db-down
        expect_anchor: dashboard.error-banner
    focus_order:                         # first N tab stops from page load
      - dashboard.header.menu-btn        # viewport-scoped entries allowed
      - dashboard.header.new-key-btn
      - dashboard.keys-table
    a11y:
      axe: [wcag2a, wcag21aa]            # axe-core rule tags; violations fail L3.S
```

Semantics:

- **S5.1 Screen presence.** Every declared route renders (2xx or declared redirect) at every declared viewport.
- **S5.2 Region structure.** The serialized accessibility tree contains the declared landmarks in the declared order, satisfying geometry constraints (bounding-box checks with the declared min/max tolerances — never exact coordinates).
- **S5.3 Component presence.** Every component anchor is present in its declared region, with its declared role, in each state where it is declared.
- **S5.4 Nothing-unexpected clause.** Undeclared *additional* components are permitted by default (regeneration may improve), EXCEPT within a region marked `closed: true`. Mark closed the regions where surprise is intolerable — primary nav is the canonical case.
- **S5.5 States are reachable and verified.** Each declared state is induced via its fixture profile and its state-scoped assertions run.
- **S5.6 Focus order** is asserted as a prefix match: the first N tab stops must match the declaration exactly. (Prefix, not total: total focus-order freezing over-constrains and breaks on any legitimate addition.)
- **S5.7 Axe.** Declared axe rule tags run per screen per state; violations are L3.S failures with the axe rule id in the detail.

The accessibility tree, not the DOM, is the structural comparison basis. DOM shape is generator-idiosyncratic (div soup varies wildly between builds); the a11y tree is the semantic skeleton and is what assistive tech actually consumes, so freezing it has independent value.

## 6. `ui/tokens.yaml`

Tokens pin visual identity without pinning pixels.

```yaml
version: 0.3
tokens:
  color:
    primary:      "#4F46E5"
    surface:      "#FFFFFF"
    surface-alt:  "#F8FAFC"
    text:         "#0F172A"
    text-muted:   "#64748B"
    danger:       "#DC2626"
    border:       "#E2E8F0"
  typography:
    font-family-base: "Inter, system-ui, sans-serif"
    scale: { sm: 14, base: 16, lg: 18, xl: 24, 2xl: 30 }   # px
  spacing:
    unit: 4                    # all gaps/padding are multiples of unit
  radius: { sm: 6, md: 8, lg: 12 }

bindings:                      # element property → token set membership
  - anchor: dashboard.header.new-key-btn
    property: background-color
    token: color.primary
  - anchor: dashboard.error-banner
    property: color
    token: color.danger
  - selector: "body"
    property: font-family
    token: typography.font-family-base

palette_conformance:
  enabled: true
  sample: [background-color, color, border-color]
  tolerance: deltaE 3          # CIEDE2000; absorbs rounding/alpha-compositing noise
  exempt_anchors: []           # e.g. third-party embeds
```

Semantics:

- **T6.1 Binding checks.** For each binding, the computed style of the resolved element must match the token value within tolerance.
- **T6.2 Palette conformance.** Sample computed values of the listed properties across all rendered elements per screen; every sampled color must be within tolerance of *some* declared color token. This is the gate that catches a generator inventing its own teal.
- **T6.3 Type scale conformance.** All computed `font-size` values must belong to the declared scale (±0.5px for rem rounding).
- **T6.4 Spacing rhythm** is `advisory` by default (reported, doesn't fail): padding/gap values as multiples of `spacing.unit`. Enforced spacing produces high false-positive rates on component-library internals; keep advisory until the substrate is proven clean.
- **T6.5** With `token_binding: css-variables`, the runner additionally asserts the custom properties exist at `:root` with declared values — cheap, and it catches hardcoding even where sampling misses.

## 7. `ui/copy.yaml`

Critical strings are declared verbatim. Microcopy drift is one of the most user-visible forms of regeneration churn and one of the cheapest to eliminate.

```yaml
version: 0.3
strings:
  cta.new-key:        "New API Key"
  empty.keys-table:   "No API keys yet. Create your first key to get started."
  error.rate-limited: "Rate limit reached. Try again in a minute."
  confirm.delete-key: "This will permanently revoke the key. This cannot be undone."
tone:                          # informative; guides unbound copy, not gated
  voice: "direct, second person, no exclamation marks"
```

Semantics:

- **C7.1** A component with a `copy:` binding must render the bound string exactly (whitespace-normalized).
- **C7.2** Copy keys referenced from `screens.yaml` or flows must exist (L1 coherence check).
- **C7.3** Unbound copy is unconstrained. Declare what matters; don't transcribe the app.
- **C7.4** Copy edits are minor spec revisions — deliberately cheap to change, because product copy legitimately iterates. The point is that it changes when a *human* changes it, not when the generator feels differently.

## 8. `ui/flows/*.flow.yaml`

Flows are the UI analogue of golden cases: executable journeys through anchored elements. They freeze *how the user gets things done* — the workflow shape — independent of what the screens look like.

```yaml
id: create-api-key
description: "User creates a key and sees it in the table"
viewport: desktop
fixture: seeded
auth: test-principal            # v0.2 testing contract
steps:
  - goto: /dashboard
  - expect: { anchor: dashboard.keys-table, visible: true }
  - click: dashboard.header.new-key-btn
  - expect: { anchor: dashboard.new-key-modal, visible: true }
  - fill:  { anchor: dashboard.new-key-modal.name-input, value: "ci-test-key" }
  - click: dashboard.new-key-modal.submit-btn
  - expect: { anchor: dashboard.new-key-modal, visible: false }
  - expect: { anchor: dashboard.keys-table, contains_text: "ci-test-key" }
  - expect_db:                   # v0.2 db_checks are legal inside flows
      delta: { query: "SELECT COUNT(*) FROM api_keys", equals: 1 }
strictness:
  no_unexpected_dialogs: true    # any undeclared dialog/modal/alert fails the flow
  max_extra_steps: 0             # generator may not insert screens into this journey
```

Semantics:

- **F8.1 Step vocabulary:** `goto`, `click`, `fill`, `press`, `select`, `hover`, `wait_for`, `expect`, `expect_db`. All element references are anchors — flows never use CSS selectors, which keeps them build-independent.
- **F8.2 Journey shape is the assertion.** `max_extra_steps: 0` means the generator cannot insert an undeclared confirmation screen, interstitial, or wizard step into this path. If a step count change is desired, it is a spec change. This is the single strongest UX-stability gate in the layer: it freezes the *number of interactions* a task costs.
- **F8.3 `no_unexpected_dialogs`** asserts absence — the flow fails if any dialog not reached via a declared step appears. Absence assertions are what catch "helpful" generator additions.
- **F8.4** Flows compose with the v0.2 DB adapter and test-auth convention; a flow is a golden case whose transport is a browser instead of HTTP.
- **F8.5** Every screen SHOULD be reachable by at least one flow; the runner reports flow coverage of the screen inventory (screens touched / screens declared).

## 9. Gate level L3 — UI Verified

```
L0 Valid      (unchanged) + ui/ files parse, anchors well-formed & unique
L1 Coherent   (unchanged) + cross-refs resolve: components→copy keys,
              flows→anchors, states→fixture profiles, bindings→tokens,
              baselines→screens/viewports/states
L2 Verified   (unchanged — HTTP-level behavioral gates)
L3 UI-Verified  requires a browser runtime against a RUNNING instance
    L3.S  structural   S5.1–S5.7
    L3.T  token        T6.1–T6.5
    L3.F  flow         F8.1–F8.5
    L3.V  visual       §10 — optional, off by default
```

Scoring extends the v0.2 coverage-weighted model: fidelity = passed/executed and coverage = executed/declared, reported per sub-gate and rolled up. Two rules:

- **L3.V never counts toward fidelity unless `ui_gates.visual: enforced`.** In `advisory` mode diffs are computed and reported but cannot fail the build.
- **Advisory checks (T6.4, and anything marked advisory) are excluded from fidelity, included in the report.**

A package without `ui/` reports L3 `not-applicable` and remains fully conformant at L2. Conformance claims are level-scoped, as in v0.2: "conformant at L3" means S, T, and F pass. V is never required for conformance (Principle 4).

## 10. Baselines and the blessing protocol

Screenshot baselines are the one place the format touches pixels, and the rules exist mostly to contain them.

`ui/baselines/manifest.yaml`:

```yaml
version: 0.3
method: ssim                    # ssim | pixelmatch
threshold: 0.98                 # per-image pass score (ssim) / max diff ratio
blessed:
  - image: dashboard.desktop.default.png
    screen: dashboard
    viewport: desktop
    state: default
    build: "sha256:9f2c…"       # hash of the build the pixels came from
    blessed_by: "nkathmann"
    blessed_at: "2026-07-05T14:12:00Z"
    masks:                       # rectangles OR anchors excluded from diff
      - anchor: dashboard.keys-table   # dynamic content
      - rect: { x: 0, y: 0, w: 1440, h: 4 }  # progress bar
```

Rules:

- **B10.1** Baselines carry provenance: the build hash they were captured from, who blessed them, when. A baseline without provenance fails L0.
- **B10.2** The runner NEVER blesses. It can *capture* candidate images (`--capture`) and emit a proposed manifest entry; a human commits it.
- **B10.3** Blessing eligibility: only a build that passed L3.S, L3.T, and L3.F may be blessed. Pixels are only ever a stricter rendering of an already-conformant structure.
- **B10.4** Masks are first-class. Dynamic regions (data tables, timestamps, avatars) are masked by anchor, which keeps masks valid across layout shifts.
- **B10.5** Comparison is perceptual (SSIM default, threshold declared), per screen × viewport × state. Anti-aliasing-level noise must not fail; a moved button must.
- **B10.6 Modes.** `off`: no capture, no compare. `advisory`: compare and report; recommended steady state — drift is *visible* on every rebuild without gating the cadence. `enforced`: diffs fail L3.V; appropriate only for regulated or white-labeled surfaces where visual change itself requires sign-off.

Why this shape: if every rebuild requires re-blessing, regeneration cadence dies and the baseline has become the asset. Advisory mode gives the operator a diff report per rebuild — "here is exactly what changed visually" — which is the actual operational need, without making pixels load-bearing.

## 11. Runner v0.3 requirements

- New dependency for L3 only: **Playwright** (chromium headless). L0–L2 continue to require pyyaml only; the runner degrades gracefully (`verify --skip-l3` or auto-skip with a loud report line when Playwright is absent).
- `verify` gains `--ui` (run L3), `--viewport <name>` (scope), `--capture <dir>` (emit candidate baselines + proposed manifest entries), `--visual {off,advisory,enforced}` (override manifest mode downward only — a CLI flag may weaken visual gating for a local run, never strengthen a claim).
- Structural comparison: serialize the accessibility tree per screen/state/viewport, normalize (strip text content except copy-bound nodes, strip generator-idiosyncratic attributes, keep roles/landmarks/anchors/order), then evaluate S5.*. The normalized tree is also written to the JSON report — it is the input to the drift metric (§13).
- Axe: inject axe-core, run declared tags, map violations to L3.S failures.
- Token checks: `getComputedStyle` via page evaluation; color comparison in CIEDE2000; `:root` custom-property assertion when `token_binding: css-variables`.
- Flows: compile step vocabulary to Playwright actions; anchor resolution is strict (`[data-testid="…"]`, exactly one match); `no_unexpected_dialogs` via dialog/route listeners armed for the whole flow.
- Report schema adds `l3: { structural: {...}, token: {...}, flow: {...}, visual: {...}, screen_flow_coverage: 0.86 }`.

## 12. Regeneration prompt contract additions

Append to the standard regeneration prompt, verbatim:

> **UI contract.** This package includes a UI contract (`ui/`). The following are binding requirements, not suggestions:
> 1. Use the declared UI substrate exactly: {ui_substrate.components} with {ui_substrate.styling}. Do not substitute component libraries.
> 2. Every element listed in the anchor manifest below MUST render with its `data-testid` set to the listed anchor, in the declared region, with the declared ARIA role.
> 3. All design token values in `ui/tokens.yaml` MUST be implemented as {ui_substrate.token_binding} and used for the bound properties. Do not introduce colors outside the declared palette or font sizes outside the declared scale.
> 4. All strings in `ui/copy.yaml` MUST be rendered verbatim where bound.
> 5. Screens must satisfy the region/landmark structure in `ui/screens.yaml`, including declared states (empty, loading, error) and the declared focus order prefix.
> 6. The user journeys in `ui/flows/` define the exact interaction sequence for each task. Do not add or remove steps, screens, or confirmation dialogs on these paths.
>
> ANCHOR MANIFEST: {generated table: anchor | screen | region | role | copy key}

The anchor manifest table is generated by the runner (`intentpkg_runner.py prompt <package_dir>`) so the prompt never drifts from the package.

## 13. Nondeterminism protocol additions

The five-run protocol gains four UI drift metrics, computed pairwise across runs:

1. **Structural drift**: tree edit distance between normalized accessibility trees, per screen, normalized by tree size. Target after gating: 0 on closed regions, near-0 elsewhere.
2. **Token conformance rate** per run (T6.2/T6.3 sample pass rate) — variance across runs measures how much visual identity the generator invents when the spec is silent.
3. **Flow stability**: flow pass rate per run, plus step-timing variance (informative).
4. **Visual variance**: pairwise SSIM distribution per screen across the five runs, masks applied — measured even when `visual: off`, because the *distribution* is the empirical map of what the UI layer still under-specifies. This is the v0.3 analogue of the v0.2 insight: the variance in unverified residue drives v0.4 of the format.

Protocol note: run the five builds *with* the UI contract in the prompt and, once per format revision, a control build *without* it. The delta between the two variance profiles is the measured value of the UI layer — the number that goes in front of skeptics.

## 14. Extraction guidance

For extract-then-regenerate on apps born without anchors:

1. Crawl declared/discovered routes at each viewport; serialize accessibility trees.
2. Derive `screens.yaml`: landmarks → regions; interactive nodes → components; propose anchors from role + accessible name (`button "New API Key"` in `banner` → `dashboard.header.new-key-btn`). Provenance: `extracted-proposed` (A4.5).
3. Derive `tokens.yaml` by clustering sampled computed styles (colors via CIEDE2000 clustering, font sizes as observed scale). Flag clusters with high spread — they are places the original app was already inconsistent; a human decides the canonical token.
4. Derive `copy.yaml` from accessible names/text of interactive and status elements. Everything else stays unbound.
5. Flows are NOT auto-extracted in v0.3. Journey intent requires a human or a session-recording source; auto-inferred flows would encode accidents as contracts. The extractor emits a flow *skeleton* per screen (goto + presence expects) as scaffolding only, marked non-normative.

## 15. Non-goals for v0.3

- **Pixel identity as conformance.** Excluded by principle, not deferred (§1, §10).
- **Animation and transition timing.** High variance, low user-perceived contract value relative to gate cost. Revisit only with evidence.
- **Fluid responsive behavior between declared viewports.** The contract is per declared viewport; intermediate widths are unconstrained in v0.3.
- **Subjective brand "feel."** Tone lives in `copy.yaml` as informative guidance; the format gates what is measurable.
- **Native mobile.** Browser surfaces only.

## 16. Open questions (carried to v0.4)

1. Should closed regions (S5.4) be the default and open the exception? Current default favors generator freedom; five-run data on structural drift in open regions should decide this empirically.
2. Anchor namespace governance once packages compose (shared component packages) — likely needs a reverse-DNS-style prefix convention.
3. Whether `screen_flow_coverage` should have a normative floor (e.g., L3 conformance requires ≥0.8) or stay reported-only.
4. Dark mode / theme variants: model as token *sets* with a variant dimension, multiplying the gate matrix — deferred until a corpus app needs it.

---

## 17. v0.3.1 changes (harness-forced, all validated against the reference build)

1. **Regions are state-scopeable** (`states: [open]`) — a region may exist
   only in declared screen states (e.g. compose only on open tickets).
2. **`focus_order` is an ordered-subsequence assertion** over the tab
   sequence, not a prefix match — packages declare the elements whose relative
   order matters without enumerating every tab stop.
3. **Token bindings take a `context`** — `{principal}` for role-conditional
   elements, `{state}` for state-scoped screens, or `{flow}` for elements
   that only exist mid-journey; flow-context bindings are checked at the flow
   step that asserts the anchor.
4. **`collection: true` anchors** may repeat (rows, messages); gates assert
   count >= 1 and per-instance properties on the first match.
5. **Role scoping**: `principals:` on screens/states and `roles:` /
   `copy_by_role:` on components, verified via the header-principal testing
   contract.
6. **`POST /__test/reset`** joins the TEST_HOOKS convention so gates run
   order-independent; the runner calls it best-effort before each screen
   state and flow.
7. **Consumption discipline** (normative for conforming builders): contract
   files are transpiled into source artifacts (tokens -> stylesheet, copy ->
   strings module, anchors -> constants); values are derived, never re-typed.
