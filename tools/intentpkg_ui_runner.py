#!/usr/bin/env python3
"""
intentpkg UI runner — L3 gates for intent packages (format v0.3).

Composes with intentpkg_runner.py (L0-L2): run both, merge --json reports.

  L3.S structural  screens render; landmarks in order; anchors present with
                   roles; collections; states (fixture/principal/hook-induced);
                   focus-order prefix; expect_absent; closed regions; titles;
                   axe-core rules
  L3.T token       :root custom properties; per-anchor bindings (deltaE, tint);
                   palette conformance sampling; type scale/weights;
                   portal palette rules (forbidden accents)
  L3.F flow        journey gates: goto/fill/click/select/expect/expect_db/http;
                   no_unexpected_dialogs; per-flow viewport; fixture refs

Usage:
  python3 intentpkg_ui_runner.py validate <package_dir>
  python3 intentpkg_ui_runner.py verify   <package_dir> --base-url URL
        [--fixtures fixtures.yaml] [--axe-js path/to/axe.min.js]
        [--json report.json] [--only S|T|F] [--violations-expected]

Deps: pyyaml, playwright (chromium). Exit 0 pass / 1 failures / 2 invalid.
Unimplemented probe kinds report `skip`, never silent-pass (coverage-weighted).
"""
import argparse, fnmatch, json, math, re, subprocess, sys, urllib.request
from pathlib import Path

try:
    import yaml
except ImportError:
    print("pyyaml required", file=sys.stderr); sys.exit(2)

# ------------------------------------------------------------------ report --
class Result:
    def __init__(self): self.checks = []
    def add(self, sub, gate, status, detail=""):
        self.checks.append({"level": "L3", "sub": sub, "gate": gate, "status": status, "detail": detail})
    def summary(self):
        out = {"sub": {}, "gates": {"pass": 0, "fail": 0, "skip": 0}}
        for s in ("S", "T", "F", "A"):
            rows = [c for c in self.checks if c["sub"] == s]
            if not rows: continue
            g = {"pass": 0, "fail": 0, "skip": 0}
            for c in rows: g[c["status"]] += 1
            ex = g["pass"] + g["fail"]
            out["sub"][{"S": "structural", "T": "token", "F": "flow", "A": "axe"}[s]] = {
                **g, "fidelity": round(g["pass"] / ex, 3) if ex else None,
                "coverage": round(ex / (ex + g["skip"]), 3) if (ex + g["skip"]) else None}
        for c in self.checks: out["gates"][c["status"]] += 1
        ex = out["gates"]["pass"] + out["gates"]["fail"]
        out["fidelity"] = round(out["gates"]["pass"] / ex, 3) if ex else None
        out["level"] = "fail" if out["gates"]["fail"] else "pass"
        return out

# ------------------------------------------------------------------- color --
def parse_color(s):
    s = s.strip()
    m = re.match(r'#([0-9a-fA-F]{6})$', s)
    if m:
        h = m.group(1); return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 1.0)
    m = re.match(r'rgba?\(([^)]+)\)', s)
    if m:
        p = [x.strip() for x in m.group(1).split(',')]
        a = float(p[3]) if len(p) > 3 else 1.0
        return (float(p[0]), float(p[1]), float(p[2]), a)
    return None

def _srgb_to_lab(rgb):
    def f(c):
        c /= 255.0
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = f(rgb[0]), f(rgb[1]), f(rgb[2])
    x = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047
    y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    z = (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883
    def g2(t): return t ** (1/3) if t > 0.008856 else (7.787 * t + 16/116)
    fx, fy, fz = g2(x), g2(y), g2(z)
    return (116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz))

def delta_e(c1, c2):
    l1, l2 = _srgb_to_lab(c1), _srgb_to_lab(c2)
    return math.dist(l1, l2)

def is_tint_of(sample, token, hue_tol=8.0, min_t=0.08):
    """sample ≈ t*token + (1-t)*white for some t in (min_t,1]."""
    ts = []
    for i in range(3):
        denom = token[i] - 255.0
        if abs(denom) < 1: continue
        ts.append((sample[i] - 255.0) / denom)
    if not ts: return delta_e(sample, token) < hue_tol
    t = sum(ts) / len(ts)
    if not (min_t < t <= 1.05): return False
    mixed = tuple(t * token[i] + (1 - t) * 255.0 for i in range(3))
    return delta_e(sample, mixed) <= hue_tol

def color_conforms(sample, tokens, tol):
    if sample[3] == 0: return True, "transparent"
    rgb = sample[:3]
    for name, hexv in tokens.items():
        tok = parse_color(hexv)[:3]
        if delta_e(rgb, tok) <= tol: return True, name
        if is_tint_of(rgb, tok): return True, f"tint({name})"
    return False, None

# ----------------------------------------------------------------- package --
class Package:
    def __init__(self, root):
        self.root = Path(root)
        self.screens = yaml.safe_load((self.root / 'ui/screens.yaml').read_text())
        self.tokens = yaml.safe_load((self.root / 'ui/tokens.yaml').read_text())
        self.copy = yaml.safe_load((self.root / 'ui/copy.yaml').read_text())['strings']
        self.manifest = yaml.safe_load((self.root / 'manifest.yaml').read_text())
        self.flows = {p.name: yaml.safe_load(p.read_text())
                      for p in sorted((self.root / 'ui/flows').glob('*.flow.yaml'))}
        jp = self.root / 'behavior/jobs.yaml'
        self.jobs = {j['id'] for j in yaml.safe_load(jp.read_text())['jobs']} if jp.exists() else set()
        self.tables = set()
        for mig in sorted((self.root / 'data/migrations').glob('*.yaml')) if (self.root / 'data/migrations').is_dir() else []:
            up = (yaml.safe_load(mig.read_text()) or {}).get('up', '') or ''
            self.tables |= {m.lower() for m in re.findall(r'create\s+table\s+(?:if\s+not\s+exists\s+)?([A-Za-z_][A-Za-z0-9_]*)', up, re.I)}
        self.viewports = {v['name']: v for v in self.manifest['ui_substrate']['viewports']}

def resolve_fixture(val, fx):
    if not isinstance(val, str): return val
    def rep(m):
        cur = fx['fixture']
        for part in m.group(0).split('.')[1:]:
            cur = cur[part]
        return str(cur)
    return re.sub(r'\$fixture\.[A-Za-z0-9_.]+', rep, val)

# ---------------------------------------------------------------- validate --
ROLE_TAGS = {
    'heading': ['H1','H2','H3','H4','H5','H6'], 'button': ['BUTTON','SUMMARY'],
    'textbox': ['TEXTAREA'], 'link': ['A'], 'table': ['TABLE'], 'row': ['TR'],
    'combobox': ['SELECT'], 'form': ['FORM'], 'paragraph': ['P'],
    'article': ['ARTICLE'], 'img': ['IMG'], 'list': ['UL','OL'], 'listitem': ['LI'],
    'group': ['FIELDSET'], 'note': ['SPAN','SMALL','DIV','DD','P'],
    'alert': [], 'status': [], 'tablist': [], 'region': ['SECTION'], 'presentation': None,
}
LANDMARK_SEL = {'banner': 'header, [role=banner]', 'main': 'main, [role=main]',
                'navigation': 'nav, [role=navigation]', 'form': 'form, [role=form]',
                'region': 'section, [role=region]', 'contentinfo': 'footer'}

def _schema_validate(pkg, res, schema_dir=None):
    """L0 schema gate: validate ui files + manifest against the spec schemas.
    Locates schemas via --schemas, $INTENTPKG_SCHEMAS, or spec/schemas beside
    the package/runner. Requires jsonschema; reports skip if unavailable."""
    import os
    cands = [schema_dir, os.environ.get('INTENTPKG_SCHEMAS'),
             pkg.root.parent / 'spec' / 'schemas', pkg.root.parent / 'schemas',
             Path(__file__).parent / 'schemas']
    sdir = next((Path(c) for c in cands if c and Path(c).is_dir()), None)
    if not sdir:
        res.add('S', 'schema:*', 'skip', 'no schema directory found (--schemas / $INTENTPKG_SCHEMAS / spec/schemas)'); return
    try:
        import json as _json
        from jsonschema import Draft202012Validator
    except ImportError:
        res.add('S', 'schema:*', 'skip', 'jsonschema not installed'); return
    schemas = {p.stem.replace('.schema', ''): _json.loads(p.read_text()) for p in sdir.glob('*.schema.json')}
    targets = [('manifest.yaml', 'manifest'), ('ui/screens.yaml', 'screens'),
               ('ui/tokens.yaml', 'tokens'), ('ui/copy.yaml', 'copy')] + \
              [(str(p.relative_to(pkg.root)), 'flow') for p in sorted((pkg.root / 'ui/flows').glob('*.flow.yaml'))]
    for rel, sname in targets:
        f = pkg.root / rel
        if not f.exists() or sname not in schemas: continue
        errs = sorted(Draft202012Validator(schemas[sname]).iter_errors(yaml.safe_load(f.read_text())),
                      key=lambda e: str(e.path))
        if errs:
            for e in errs[:10]:
                res.add('S', f'schema:{rel}', 'fail', f"{'/'.join(map(str, e.path)) or '<root>'}: {e.message[:140]}")
        else:
            res.add('S', f'schema:{rel}', 'pass', sname)

def validate(pkg, res, schema_dir=None):
    _schema_validate(pkg, res, schema_dir)
    anchors, errs = {}, []
    for scr in pkg.screens['screens']:
        seen, regions = set(), {r['id'] for r in scr['regions']}
        for c in scr.get('components', []):
            a = c['anchor']
            if a in seen and not c.get('collection'): errs.append(f"dup anchor {a}")
            seen.add(a); anchors[a] = (scr, c)
            if not a.startswith(scr['id'] + '.'): errs.append(f"{a}: bad prefix")
            if c.get('region') not in regions: errs.append(f"{a}: unknown region")
            for k in [c.get('copy')] + list(c.get('copy_by_role', {}).values()):
                if k and k not in pkg.copy: errs.append(f"{a}: unknown copy key {k}")
        for st in scr.get('states', []):
            if 'setup_hook' in st and st['setup_hook']['job'] not in pkg.jobs:
                errs.append(f"{scr['id']}.{st['id']}: unknown job")
            for ea in st.get('expect_absent', []):
                if ea not in anchors: errs.append(f"{scr['id']}: expect_absent unknown {ea}")
        for fo in scr.get('focus_order', []):
            if fo not in anchors: errs.append(f"{scr['id']}: focus_order unknown {fo}")
    for b in pkg.tokens.get('bindings', []):
        if 'anchor' in b and b['anchor'] not in anchors: errs.append(f"binding unknown anchor {b['anchor']}")
    for name, flow in pkg.flows.items():
        for step in flow['steps']:
            verb, val = next(iter(step.items()))
            refs = ([val] if isinstance(val, str) else [val.get('anchor')]) if verb in ('click','hover') \
                   else ([val['anchor']] if isinstance(val, dict) and 'anchor' in val else [])
            refs = [r for r in refs if r]
            for a in refs:
                if a not in anchors: errs.append(f"{name}: unknown anchor {a}")
            if verb == 'http':
                m = re.match(r'/__test/jobs/([a-z0-9-]+)/run', val['path'])
                if m and m.group(1) not in pkg.jobs: errs.append(f"{name}: unknown job {m.group(1)}")
            if verb == 'expect' and isinstance(val, dict) and val.get('copy') and val['copy'] not in pkg.copy:
                errs.append(f"{name}: unknown copy key {val['copy']}")
            if verb == 'expect_db' and pkg.tables:
                q = (val.get('delta') or val.get('equals') or {}).get('query', '')
                for t in re.findall(r'\b(?:from|join)\s+([A-Za-z_][A-Za-z0-9_]*)', q, re.I):
                    if t.lower() not in pkg.tables:
                        errs.append(f"{name}: expect_db references table '{t}' not created by any migration")
    for e in errs: res.add('S', 'validate', 'fail', e)
    if not errs: res.add('S', 'validate:ui-coherence', 'pass', f"{len(anchors)} anchors, {len(pkg.flows)} flows")
    return anchors, not errs

# ------------------------------------------------------------------ verify --
class Verifier:
    def __init__(self, pkg, base, fixtures, res, axe_js=None):
        self.pkg, self.base, self.fx, self.res, self.axe = pkg, base.rstrip('/'), fixtures, res, axe_js
        self.roles = fixtures.get('principal_roles', {})
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        self.browser = self._pw.chromium.launch(headless=True)
        self._pages = {}   # (principal, viewport) -> page

    def close(self):
        self.browser.close(); self._pw.stop()

    def page(self, principal, viewport):
        key = (principal, viewport)
        if key not in self._pages:
            vp = self.pkg.viewports[viewport]
            hdrs = {} if principal in (None, 'anonymous') else {'x-test-principal': principal}
            ctx = self.browser.new_context(viewport={'width': vp['width'], 'height': vp['height']},
                                           extra_http_headers=hdrs)
            self._pages[key] = ctx.new_page()
        return self._pages[key]

    def http(self, method, path, principal=None):
        req = urllib.request.Request(self.base + path, method=method, data=b'')
        if principal: req.add_header('x-test-principal', principal)
        try:
            with urllib.request.urlopen(req, timeout=15) as r: return r.status
        except urllib.error.HTTPError as e: return e.code
        except Exception: return 599

    def db(self, query):
        cmd = self.fx['db']['command']
        argv = [a if a != '{query}' else query for a in cmd.split(' ')]
        out = subprocess.run(argv, capture_output=True, text=True, timeout=20)
        return out.stdout.strip()

    # ---------------------------------------------------------------- L3.S --
    def verify_structural(self):
        for scr in self.pkg.screens['screens']:
            for st in scr.get('states', [{'id': 'default', 'fixture': 'seeded'}]):
                principals = st.get('principals') or scr.get('principals') or ['anonymous']
                for pr in principals:
                    for vpn in self.pkg.viewports:
                        self._screen_state(scr, st, pr, vpn)

    def _route(self, scr, st):
        r = scr['route']
        if 'route_binding' in st:
            r = re.sub(r'\{[a-z_]+\}', resolve_fixture(st['route_binding'], self.fx), r)
        return r

    def _screen_state(self, scr, st, pr, vpn):
        gid = f"screen:{scr['id']}:{st['id']}:{pr}:{vpn}"
        self.http('POST', '/__test/reset')  # best-effort; 404 tolerated
        if 'setup_hook' in st:
            code = self.http('POST', f"/__test/jobs/{st['setup_hook']['job']}/run", pr)
            if code >= 400:
                self.res.add('S', gid + ':setup-hook', 'fail', f"hook returned {code}"); return
        page = self.page(pr, vpn)
        try:
            resp = page.goto(self.base + self._route(scr, st), wait_until='load', timeout=15000)
        except Exception as e:
            self.res.add('S', gid, 'fail', f"navigation error: {e}"); return
        ok = resp and resp.status < 400
        self.res.add('S', gid + ':renders', 'pass' if ok else 'fail', f"status {resp.status if resp else '?'}")
        if not ok: return
        # title
        if 'title' in scr:
            t = page.title()
            self.res.add('S', gid + ':title', 'pass' if t == scr['title'] else 'fail', t)
        elif 'title_pattern' in scr:
            t = page.title()
            self.res.add('S', gid + ':title', 'pass' if fnmatch.fnmatch(t, scr['title_pattern']) else 'fail', t)
        # regions / landmarks (order among visible, viewport-applicable regions)
        expected, hidden_regions = [], []
        for r in scr['regions']:
            if r.get('viewports') and vpn not in r['viewports']: continue
            if r.get('states') and st['id'] not in r['states']: continue
            (hidden_regions if r.get('initially') == 'hidden' else expected).append(r)
        found_pos = []
        for r in expected:
            sel = LANDMARK_SEL.get(r['landmark'], f"[role={r['landmark']}]")
            loc = page.locator(sel)
            vis = [i for i in range(loc.count()) if loc.nth(i).is_visible()]
            if not vis:
                self.res.add('S', gid + f":region:{r['id']}", 'fail', f"no visible {r['landmark']}")
            else:
                self.res.add('S', gid + f":region:{r['id']}", 'pass', '')
                found_pos.append(loc.nth(vis[0]).evaluate(
                    "e => Array.from(document.querySelectorAll('*')).indexOf(e)"))
            if r.get('geometry'): self.res.add('S', gid + f":region:{r['id']}:geometry", 'skip', 'geometry checks not implemented in v0.3 runner')
            if r.get('closed'):
                sel2 = LANDMARK_SEL.get(r['landmark'], 'nav')
                n = page.locator(sel2 + ' >> css=a, ' + sel2 + ' >> css=button').count()
                declared = sum(1 for c in scr.get('components', []) if c.get('region') == r['id'])
                if declared == 0:
                    self.res.add('S', gid + f":region:{r['id']}:closed", 'skip', 'closed region with no declared components on this screen')
                else:
                    self.res.add('S', gid + f":region:{r['id']}:closed",
                                  'pass' if n <= declared else 'fail',
                                  f"{n} interactive vs {declared} declared")
        if len(found_pos) > 1:
            self.res.add('S', gid + ':region-order', 'pass' if found_pos == sorted(found_pos) else 'fail', str(found_pos))
        for r in hidden_regions:
            sel = f"[data-testid='{next((c['anchor'] for c in scr['components'] if c.get('region')==r['id']), '')}']"
            # assert the drawer region itself is not visible pre-reveal
            drawer = page.locator(f"[data-region='{r['id']}']")
            hidden_ok = drawer.count() == 0 or not drawer.first.is_visible()
            self.res.add('S', gid + f":region:{r['id']}:initially-hidden", 'pass' if hidden_ok else 'fail', '')
            if r.get('revealed_by'):
                btn = page.locator(f"[data-testid='{r['revealed_by']}']")
                if btn.count() and btn.first.is_visible():
                    btn.first.click()
                    now_vis = drawer.count() and drawer.first.is_visible()
                    self.res.add('S', gid + f":region:{r['id']}:revealed", 'pass' if now_vis else 'fail', '')
                    page.goto(self.base + self._route(scr, st))  # reset
                else:
                    self.res.add('S', gid + f":region:{r['id']}:revealed", 'skip', 'revealer not visible on this viewport')
        # components
        my_role = self.roles.get(pr)
        for c in scr.get('components', []):
            self._component(page, scr, st, pr, vpn, my_role, c, gid)
        # expect_absent
        for ea in st.get('expect_absent', []):
            loc = page.locator(f"[data-testid='{ea}']")
            absent = loc.count() == 0 or not loc.first.is_visible()
            self.res.add('S', gid + f":absent:{ea}", 'pass' if absent else 'fail', '')
        # focus order (desktop only)
        fo = scr.get('focus_order')
        if fo and vpn == 'desktop':
            page.goto(self.base + self._route(scr, st))
            got = []
            for _ in range(len(fo) + 10):
                page.keyboard.press('Tab')
                tid = page.evaluate(
                    "() => { const e = document.activeElement.closest('[data-testid]'); return e ? e.dataset.testid : null }")
                if tid: got.append(tid)
                if len(got) and got[-1] == fo[-1] and all(x in got for x in fo): break
            it = iter(got)
            ok = all(any(x == want for x in it) for want in fo)  # ordered subsequence
            self.res.add('S', gid + ':focus-order', 'pass' if ok else 'fail', f"tab sequence {got}")
        # axe
        if self.axe and vpn == 'desktop':
            tags = (scr.get('a11y') or {}).get('axe')
            if tags:
                try:
                    page.add_script_tag(content=Path(self.axe).read_text())
                    r = page.evaluate("tags => axe.run(document, {runOnly: {type: 'tag', values: tags}})", tags)
                    v = r['violations']
                    self.res.add('A', gid + ':axe', 'pass' if not v else 'fail',
                                  '; '.join(f"{x['id']}({len(x['nodes'])})" for x in v[:5]))
                except Exception as e:
                    self.res.add('A', gid + ':axe', 'skip', f"axe error: {e}")

    def _component(self, page, scr, st, pr, vpn, my_role, c, gid):
        a = c['anchor']
        cid = gid + f":anchor:{a}"
        if c.get('viewports') and vpn not in c['viewports']: return
        if c.get('roles') and my_role:
            if my_role not in c['roles']:
                loc = page.locator(f"[data-testid='{a}']")
                absent = loc.count() == 0 or not loc.first.is_visible()
                self.res.add('S', cid + ':role-scoped-absent', 'pass' if absent else 'fail',
                              f"must be absent for role {my_role}")
                return
        if c.get('state') and c['state'] != st['id']: return
        if c.get('states_visible') and st['id'] not in c['states_visible']:
            loc = page.locator(f"[data-testid='{a}']")
            absent = loc.count() == 0 or not loc.first.is_visible()
            self.res.add('S', cid + ':state-hidden', 'pass' if absent else 'fail', f"hidden in state {st['id']}")
            return
        if c.get('state_scope'):
            self.res.add('S', cid, 'skip', f"state_scope {c['state_scope']} — verified via flow"); return
        loc = page.locator(f"[data-testid='{a}']")
        n = loc.count()
        if c.get('optional') and n == 0:
            self.res.add('S', cid, 'skip', 'optional, not present under fixture'); return
        want = 'n>=1' if c.get('collection') else 'n==1'
        ok = n >= 1 if c.get('collection') else n == 1
        self.res.add('S', cid, 'pass' if ok else 'fail', f"count {n} ({want})")
        if not ok: return
        # role
        role = c.get('role')
        if role and role != 'presentation':
            el = loc.first
            actual_role = el.get_attribute('role')
            tag = el.evaluate('e => e.tagName')
            itype = (el.get_attribute('type') or '').lower()
            tags = ROLE_TAGS.get(role, [])
            ok = (actual_role == role or tag in (tags or [])
                  or (role == 'textbox' and tag == 'INPUT' and itype in ('text', 'password', 'email', ''))
                  or (role == 'button' and tag == 'INPUT' and itype in ('submit', 'button'))
                  or (role == 'button' and tag == 'A' and actual_role == 'button'))
            self.res.add('S', cid + ':role', 'pass' if ok else 'fail', f"tag {tag} role {actual_role} want {role}")
        # copy
        key = c.get('copy') or (c.get('copy_by_role') or {}).get(my_role)
        if key:
            wanttext = self.pkg.copy[key]
            got = ' '.join(loc.first.inner_text().split())
            self.res.add('S', cid + ':copy', 'pass' if got == wanttext else 'fail', f"got {got!r}")
        # table columns (subsequence of header cells)
        if c.get('columns'):
            ths = [t.strip().lower() for t in loc.first.locator('th').all_inner_texts()]
            it, ok = iter(ths), True
            for col in c['columns']:
                if not any(col.lower() in h for h in it): ok = False; break
            self.res.add('S', cid + ':columns', 'pass' if ok else 'fail', f"headers {ths}")
        # select options
        if c.get('options') and c.get('role') == 'combobox':
            vals = loc.first.locator('option').evaluate_all('els => els.map(e => e.value)')
            self.res.add('S', cid + ':options', 'pass' if vals == c['options'] else 'fail', str(vals))
        # chronological collections
        if c.get('order') == 'chronological':
            ts = loc.evaluate_all("els => els.map(e => e.dataset.ts).filter(Boolean)")
            ok = ts == sorted(ts) and len(ts) == n
            self.res.add('S', cid + ':order', 'pass' if ok else ('skip' if not ts else 'fail'),
                          'data-ts missing' if not ts else '')

    # ---------------------------------------------------------------- L3.T --
    def _screen_page(self, screen_id, state_id=None, principal=None):
        scr = next(s for s in self.pkg.screens['screens'] if s['id'] == screen_id)
        states = scr.get('states', [{'id': 'default'}])
        st = next((s for s in states if s['id'] == state_id), states[0])
        pr = principal or (st.get('principals') or scr.get('principals') or ['anonymous'])[0]
        self.http('POST', '/__test/reset')
        if 'setup_hook' in st: self.http('POST', f"/__test/jobs/{st['setup_hook']['job']}/run", pr)
        page = self.page(pr, 'desktop')
        page.goto(self.base + self._route(scr, st))
        return page, scr

    def verify_tokens(self):
        colors = self.pkg.tokens['tokens']['color']
        # :root custom properties (css-variables binding contract)
        page, _ = self._screen_page('login')
        for name, hexv in colors.items():
            got = page.evaluate(f"() => getComputedStyle(document.documentElement).getPropertyValue('--color-{name}').trim()")
            ok = got.lower() == hexv.lower() or (parse_color(got) and delta_e(parse_color(got)[:3], parse_color(hexv)[:3]) < 1)
            self.res.add('T', f"root-var:--color-{name}", 'pass' if ok else 'fail', f"got {got!r}")
        # bindings
        for b in self.pkg.tokens.get('bindings', []):
            self._binding(b, colors)
        # palette + type conformance per screen (default state, desktop)
        pconf = self.pkg.tokens.get('palette_conformance', {})
        tol = float(str(pconf.get('tolerance', 'deltaE 3')).split()[-1])
        exempt = pconf.get('exempt_anchors', [])
        rules = {r['portal']: r for r in self.pkg.tokens.get('portal_palette_rules', [])}
        scale = set(self.pkg.tokens['tokens']['typography']['scale'].values())
        weights = set(self.pkg.tokens['tokens']['typography'].get('weights', [400, 500, 600]))
        for scr in self.pkg.screens['screens']:
            page, _ = self._screen_page(scr['id'])
            sample = page.evaluate("""(exempt) => {
                const out = [];
                for (const e of document.body.querySelectorAll('*')) {
                  if (exempt.some(x => e.closest(`[data-testid="${x}"]`))) continue;
                  const cs = getComputedStyle(e);
                  if (cs.display === 'none' || cs.visibility === 'hidden') continue;
                  const id = e.dataset.testid || e.tagName;
                  out.push({id, bg: cs.backgroundColor, fg: cs.color, bd: cs.borderTopColor,
                            fs: parseFloat(cs.fontSize), fw: cs.fontWeight,
                            text: e.childNodes.length && Array.from(e.childNodes).some(n => n.nodeType===3 && n.textContent.trim())});
                }
                return out; }""", exempt)
            bad_colors, forbidden_hits, bad_fs, bad_fw = [], [], [], []
            forb = [parse_color(self._tok(t))[:3] for t in rules.get(scr.get('portal', ''), {}).get('forbidden_tokens', [])]
            for s in sample:
                for prop in ('bg', 'fg', 'bd'):
                    col = parse_color(s[prop])
                    if not col or col[3] == 0: continue
                    ok, _m = color_conforms(col, colors, tol)
                    if not ok: bad_colors.append(f"{s['id']}:{prop}={s[prop]}")
                    for f in forb:
                        if delta_e(col[:3], f) <= tol or is_tint_of(col[:3], f, min_t=0.25):
                            forbidden_hits.append(f"{s['id']}:{prop}")
                if s['text']:
                    if not any(abs(s['fs'] - v) <= 0.5 for v in scale): bad_fs.append(f"{s['id']}:{s['fs']}px")
                    if int(s['fw']) not in weights: bad_fw.append(f"{s['id']}:{s['fw']}")
            self.res.add('T', f"palette:{scr['id']}", 'pass' if not bad_colors else 'fail',
                          '; '.join(sorted(set(bad_colors))[:6]))
            if forb:
                self.res.add('T', f"portal-palette:{scr['id']}", 'pass' if not forbidden_hits else 'fail',
                              '; '.join(sorted(set(forbidden_hits))[:6]))
            self.res.add('T', f"type-scale:{scr['id']}", 'pass' if not bad_fs else 'fail', '; '.join(sorted(set(bad_fs))[:6]))
            self.res.add('T', f"type-weight:{scr['id']}", 'pass' if not bad_fw else 'fail', '; '.join(sorted(set(bad_fw))[:6]))

    def _tok(self, path):
        cur = self.pkg.tokens['tokens']
        for p in path.split('.'): cur = cur[p]
        return cur

    def _binding(self, b, colors):
        prop = b['property']
        css = prop  # camel not needed; use getPropertyValue
        if 'selector' in b:
            page, _ = self._screen_page('ticket-list')
            loc = page.locator(b['selector'])
            gate = f"binding:{b['selector']}:{prop}"
            self._binding_check(loc, css, b['token'], gate)
            return
        a = b['anchor']
        screen_id = a.split('.')[0]
        ctx = b.get('context', {})
        if ctx.get('flow'):
            return  # verified inside the named flow; registered in verify_flows
        if 'token_by_state' in b:
            for stid, tok in b['token_by_state'].items():
                page, scr = self._screen_page(screen_id, stid)
                loc = page.locator(f"[data-testid='{a}']")
                gate = f"binding:{a}:{prop}@{stid}"
                if loc.count() == 0:
                    self.res.add('T', gate, 'fail', 'anchor not found'); continue
                self._binding_check(loc, css, tok, gate, tint_ok=bool(b.get('tint_tolerance')))
        else:
            page, scr = self._screen_page(screen_id, ctx.get('state'), ctx.get('principal'))
            loc = page.locator(f"[data-testid='{a}']")
            gate = f"binding:{a}:{prop}"
            if loc.count() == 0:
                self.res.add('T', gate, 'fail', 'anchor not found'); return
            self._binding_check(loc, css, b['token'], gate)

    def _binding_check(self, loc, cssprop, token_path, gate, tint_ok=False):
        got = loc.first.evaluate(f"e => getComputedStyle(e).getPropertyValue('{cssprop}')").strip()
        tokval = self._tok(token_path)
        if cssprop == 'font-family':
            ok = [f.strip().strip('"\'').lower() for f in got.split(',')][:2] == \
                 [f.strip().strip('"\'').lower() for f in tokval.split(',')][:2]
            self.res.add('T', gate, 'pass' if ok else 'fail', f"got {got!r}"); return
        gc, tc = parse_color(got), parse_color(tokval)
        if not gc or not tc:
            self.res.add('T', gate, 'skip', f"non-color property compare not implemented ({got!r})"); return
        ok = delta_e(gc[:3], tc[:3]) <= 3 or (tint_ok and is_tint_of(gc[:3], tc[:3]))
        self.res.add('T', gate, 'pass' if ok else 'fail', f"got {got}")

    # ---------------------------------------------------------------- L3.F --
    def verify_flows(self):
        self._flow_bindings = {}
        for b in self.pkg.tokens.get('bindings', []):
            fl = (b.get('context') or {}).get('flow')
            if fl: self._flow_bindings.setdefault(fl, []).append(b)
        for name, flow in self.pkg.flows.items():
            self._flow(name, flow)

    def _flow(self, name, flow):
        gid = f"flow:{flow['id']}"
        vp = self.pkg.viewports[flow.get('viewport', 'desktop')]
        auth = flow.get('auth')
        pr = auth['principal'] if isinstance(auth, dict) else None
        hdrs = {'x-test-principal': pr} if pr else {}
        ctx = self.browser.new_context(viewport={'width': vp['width'], 'height': vp['height']},
                                       extra_http_headers=hdrs)
        page = ctx.new_page()
        self.http('POST', '/__test/reset')  # best-effort; 404 tolerated
        dialogs = []
        page.on('dialog', lambda d: (dialogs.append(d.message), d.dismiss()))
        deltas = {}
        for step in flow['steps']:
            if 'expect_db' in step and 'delta' in step['expect_db']:
                q = resolve_fixture(step['expect_db']['delta']['query'], self.fx)
                deltas[q] = float(self.db(q) or 0)
        self._current_flow = flow['id']
        self._flow_binding_done = set()
        failed = False
        for i, step in enumerate(flow['steps']):
            verb, val = next(iter(step.items()))
            sid = f"{gid}:step{i+1}:{verb}"
            try:
                ok, detail = self._step(page, verb, val, deltas, pr)
            except Exception as e:
                ok, detail = False, f"error: {e}"
            self.res.add('F', sid, 'pass' if ok else 'fail', detail)
            if not ok: failed = True; break
        strict = flow.get('strictness', {})
        if strict.get('no_unexpected_dialogs'):
            self.res.add('F', gid + ':no-unexpected-dialogs', 'pass' if not dialogs else 'fail',
                          '; '.join(dialogs[:3]))
        ctx.close()
        if not failed:
            self.res.add('F', gid, 'pass', f"{len(flow['steps'])} steps")

    def _step(self, page, verb, val, deltas, principal):
        rf = lambda v: resolve_fixture(v, self.fx)
        if verb == 'goto':
            r = page.goto(self.base + rf(val), wait_until='load', timeout=15000)
            return (r and r.status < 400), f"status {r.status if r else '?'}"
        if verb in ('click', 'hover'):
            if isinstance(val, dict):
                loc = page.locator(f"[data-testid='{val['anchor']}']")
                if val.get('text'): loc = loc.filter(has_text=rf(val['text']))
                loc = loc.nth(val.get('nth', 0))
                if not loc.count(): return False, 'anchor (with qualifier) not found'
                target = loc
            else:
                loc = page.locator(f"[data-testid='{val}']")
                if not loc.count(): return False, 'anchor not found'
                target = loc.first
            getattr(target, verb)()
            try: page.wait_for_load_state('load', timeout=5000)
            except Exception: pass
            return True, ''
        if verb == 'fill':
            loc = page.locator(f"[data-testid='{val['anchor']}']")
            if not loc.count(): return False, 'anchor not found'
            loc.first.fill(rf(val['value'])); return True, ''
        if verb == 'select':
            loc = page.locator(f"[data-testid='{val['anchor']}']")
            loc.first.select_option(rf(val['value'])); return True, ''
        if verb == 'press':
            page.keyboard.press(val); return True, ''
        if verb == 'wait_for':
            page.wait_for_selector(f"[data-testid='{rf(val)}']", timeout=10000); return True, ''
        if verb == 'http':
            code = self.http(val.get('method', 'POST'), rf(val['path']), principal)
            return code < 400, f"status {code}"
        if verb == 'expect_db':
            if 'delta' in val:
                q = rf(val['delta']['query'])
                after = float(self.db(q) or 0)
                want = float(val['delta']['equals'])
                got = after - deltas.get(q, 0)
                return got == want, f"delta {got} want {want}"
            q = rf(val['equals']['query'])
            got = self.db(q)
            return got == str(val['equals']['value']), f"got {got!r}"
        if verb == 'expect':
            if 'url_path' in val:
                try: page.wait_for_load_state('load', timeout=8000)
                except Exception: pass
                from urllib.parse import urlparse
                p = urlparse(page.url).path
                return p == val['url_path'], f"path {p}"
            wants_presence = val.get('visible') is True or any(
                k in val for k in ('copy', 'contains_text', 'count_min', 'text_not_empty', 'value'))
            if wants_presence:
                try: page.wait_for_selector(f"[data-testid='{val['anchor']}']", state='attached', timeout=8000)
                except Exception: pass
            loc = page.locator(f"[data-testid='{val['anchor']}']")
            if 'visible' in val:
                vis = loc.count() > 0 and loc.first.is_visible()
                if vis != val['visible']: return False, f"visible={vis}"
            if val.get('copy'):
                want = self.pkg.copy[val['copy']]
                got = ' '.join(loc.first.inner_text().split()) if loc.count() else ''
                if got != want: return False, f"copy got {got!r}"
            if 'contains_text' in val:
                t = rf(val['contains_text'])
                if not loc.filter(has_text=t).count() and t not in (loc.first.inner_text() if loc.count() else ''):
                    return False, f"text {t!r} not found"
            if 'not_contains_text' in val:
                t = rf(val['not_contains_text'])
                if loc.count() and loc.filter(has_text=t).count(): return False, f"text {t!r} present but forbidden"
            if 'count_min' in val:
                if loc.count() < val['count_min']: return False, f"count {loc.count()}"
            if val.get('text_not_empty'):
                if not (loc.count() and loc.first.inner_text().strip()): return False, 'empty text'
            if 'value' in val:
                got = loc.first.input_value()
                if got != rf(val['value']): return False, f"value {got!r}"
            for b in getattr(self, '_flow_bindings', {}).get(getattr(self, '_current_flow', None), []):
                if b['anchor'] == val.get('anchor') and id(b) not in self._flow_binding_done and loc.count():
                    self._flow_binding_done.add(id(b))
                    self._binding_check(loc, b['property'], b['token'],
                                        f"binding:{b['anchor']}:{b['property']}@flow:{self._current_flow}")
            return True, ''
        return False, f"unknown verb {verb}"

# -------------------------------------------------------------------- main --
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('command', choices=['validate', 'verify'])
    ap.add_argument('package')
    ap.add_argument('--base-url'); ap.add_argument('--fixtures')
    ap.add_argument('--axe-js'); ap.add_argument('--json'); ap.add_argument('--schemas')
    ap.add_argument('--only', choices=['S', 'T', 'F'])
    args = ap.parse_args()

    pkg, res = Package(args.package), Result()
    anchors, ok = validate(pkg, res, args.schemas)
    ok = ok and not any(c['status'] == 'fail' for c in res.checks)
    if args.command == 'validate' or not ok:
        s = res.summary(); print(json.dumps(s, indent=2))
        sys.exit(0 if ok else 2)

    fixtures = yaml.safe_load(Path(args.fixtures).read_text()) if args.fixtures else \
               yaml.safe_load((Path(args.package) / 'fixtures.example.yaml').read_text())
    v = Verifier(pkg, args.base_url, fixtures, res, axe_js=args.axe_js)
    try:
        if args.only in (None, 'S'): v.verify_structural()
        if args.only in (None, 'T'): v.verify_tokens()
        if args.only in (None, 'F'): v.verify_flows()
    finally:
        v.close()
    s = res.summary()
    report = {"summary": s, "checks": res.checks}
    if args.json: Path(args.json).write_text(json.dumps(report, indent=2))
    print(json.dumps(s, indent=2))
    for c in res.checks:
        if c['status'] == 'fail': print(f"  ✗ [{c['sub']}] {c['gate']} — {c['detail']}")
    sys.exit(1 if s['gates']['fail'] else 0)

if __name__ == '__main__':
    main()
