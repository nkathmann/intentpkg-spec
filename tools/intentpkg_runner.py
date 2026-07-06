#!/usr/bin/env python3
"""
intentpkg runner — conformance gate for intent packages (format v0.2).

Levels:
  L0 Valid     package structure, YAML parses, provenance present on assertions
  L1 Coherent  cross-file references resolve (goldens -> OpenAPI, refs, migrations)
  L2 Verified  behavioral gates pass against a RUNNING instance (goldens +
               invariant probes). Requires --base-url. Fixtures via --fixtures.

v0.2 additions:
  - DB adapter: fixtures.yaml may define a top-level `db:` block; `db_checks`
    in any gate's expect become executable (delta = before/after numeric diff,
    equals = post-state comparison).
        db:
          mode: command        # zero-dependency: shells out, {query} is one argv
          command: "docker exec roundtrip-pg psql -U postgres -d dandi -tAc {query}"
        # or: mode: psycopg, dsn: postgres://... (needs psycopg/psycopg2 installed)
  - body_not_contains: assert a substring is ABSENT from the raw response body
  - body_schema: inline JSON-schema subset in expect (alongside body_schema_ref)
  - coverage-weighted scoring: fidelity AND probe coverage reported side by side

Usage:
  python3 intentpkg_runner.py validate <package_dir>
  python3 intentpkg_runner.py verify   <package_dir> --base-url http://localhost:3000 [--fixtures fixtures.yaml] [--json report.json]

Dependencies: pyyaml only (stdlib otherwise). Schema checking implements the
JSON-Schema subset the format uses (type/required/properties/items/min-max).

Exit codes: 0 all requested levels pass; 1 failures; 2 package invalid.
"""

import argparse
import json
import re
import shlex
import ssl
import subprocess
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

try:
    import yaml
except ImportError:
    print("pyyaml required: pip install pyyaml", file=sys.stderr)
    sys.exit(2)

# ---------------------------------------------------------------- results ----

class Result:
    def __init__(self):
        self.checks = []          # dicts: level, gate, status(pass|fail|skip), detail

    def add(self, level, gate, status, detail=""):
        self.checks.append({"level": level, "gate": gate, "status": status, "detail": detail})

    def level_status(self, level):
        rows = [c for c in self.checks if c["level"] == level]
        if not rows:
            return "not-run"
        if any(c["status"] == "fail" for c in rows):
            return "fail"
        return "pass"

    def summary(self):
        out = {"levels": {}, "gates": {"pass": 0, "fail": 0, "skip": 0}}
        for lv in ("L0", "L1", "L2"):
            out["levels"][lv] = self.level_status(lv)
        for c in self.checks:
            out["gates"][c["status"]] += 1
        executed = out["gates"]["pass"] + out["gates"]["fail"]
        out["fidelity"] = round(out["gates"]["pass"] / executed, 3) if executed else None
        # coverage: how much of the declared assertion surface actually executed.
        # L2-only, because L0/L1 are always executable by construction.
        l2 = [c for c in self.checks if c["level"] == "L2"]
        l2_exec = sum(1 for c in l2 if c["status"] in ("pass", "fail"))
        out["l2_coverage"] = round(l2_exec / len(l2), 3) if l2 else None
        out["coverage_note"] = f'{out["gates"]["skip"]} gate(s) skipped (no probe/fixture/adapter)'
        return out

# ------------------------------------------------------------- pkg loading ---

REQUIRED = [
    "manifest.yaml", "intent.md",
    "data/entities.yaml",
    "interface/api.openapi.yaml", "interface/surfaces.yaml",
    "behavior/invariants.yaml",
]

def load_yaml(path):
    return yaml.safe_load(path.read_text())

def load_package(pkg_dir, res):
    pkg = {"dir": pkg_dir, "yaml": {}, "features": [], "goldens": []}
    ok = True
    for rel in REQUIRED:
        p = pkg_dir / rel
        if not p.exists():
            res.add("L0", f"exists:{rel}", "fail", "required file missing")
            ok = False
    for p in sorted(pkg_dir.rglob("*.yaml")) + sorted(pkg_dir.rglob("*.yml")) + [pkg_dir / "provenance.lock"]:
        if not p.exists() or p.is_dir():
            continue
        rel = str(p.relative_to(pkg_dir))
        try:
            pkg["yaml"][rel] = load_yaml(p)
            res.add("L0", f"yaml:{rel}", "pass")
        except yaml.YAMLError as e:
            res.add("L0", f"yaml:{rel}", "fail", str(e).splitlines()[0])
            ok = False
    for p in sorted(pkg_dir.rglob("*.feature")):
        rel = str(p.relative_to(pkg_dir))
        text = p.read_text()
        if not re.search(r"^\s*Feature:", text, re.M):
            res.add("L0", f"gherkin:{rel}", "fail", "no Feature: header")
            ok = False
        else:
            res.add("L0", f"gherkin:{rel}", "pass")
            pkg["features"].append((rel, text))
    for rel, doc in pkg["yaml"].items():
        if rel.startswith("behavior/golden/") and isinstance(doc, list):
            for case in doc:
                case["_src"] = rel
                pkg["goldens"].append(case)
    return pkg if ok else None

# ------------------------------------------------------------------- L0 ------

def check_l0(pkg, res):
    man = pkg["yaml"].get("manifest.yaml") or {}
    fmt = str(man.get("format", ""))
    res.add("L0", "manifest:format", "pass" if fmt.startswith("intentpkg/") else "fail", fmt)
    if not (man.get("app", {}) or {}).get("id"):
        res.add("L0", "manifest:app.id", "fail", "missing app.id")
    else:
        res.add("L0", "manifest:app.id", "pass")

    # provenance presence on contract assertions
    ents = (pkg["yaml"].get("data/entities.yaml") or {}).get("entities", {}) or {}
    for name, ent in ents.items():
        st = "pass" if isinstance(ent, dict) and "provenance" in ent else "fail"
        res.add("L0", f"provenance:entity:{name}", st)
    invdoc = pkg["yaml"].get("behavior/invariants.yaml") or {}
    invs = invdoc.get("invariants", invdoc if isinstance(invdoc, list) else []) or []
    for inv in invs:
        st = "pass" if "provenance" in inv else "fail"
        res.add("L0", f"provenance:{inv.get('id','?')}", st)
    pkg["invariants"] = invs

# ------------------------------------------------------------------- L1 ------

def openapi_paths(pkg):
    api = pkg["yaml"].get("interface/api.openapi.yaml") or {}
    return api.get("paths", {}) or {}

def check_l1(pkg, res):
    paths = openapi_paths(pkg)

    # goldens reference real paths; schema_refs resolve
    for case in pkg["goldens"]:
        name = case.get("name", "?")
        p = (case.get("request") or {}).get("path", "").split("?", 1)[0]
        norm = re.sub(r"/[0-9a-f-]{8,}", "/{id}", p)
        hit = p in paths or norm in paths or any(
            re.fullmatch(re.sub(r"\{[^}]+\}", "[^/]+", k), p) for k in paths)
        res.add("L1", f"golden->path:{name}", "pass" if hit else "fail", p)
        ref = (case.get("expect") or {}).get("body_schema_ref")
        if ref:
            # JSON-pointer semantics: split on '/' FIRST, then decode ~1 -> / per segment
            target = [seg.replace("~1", "/").replace("~0", "~")
                      for seg in ref.split("#", 1)[-1].strip("/").split("/")]
            node = pkg["yaml"].get(ref.split("#", 1)[0]) or {}
            ok = True
            for part in target:
                if isinstance(node, dict) and part in node:
                    node = node[part]
                else:
                    ok = False
                    break
            res.add("L1", f"golden->schema_ref:{name}", "pass" if ok else "fail", ref)

    # entity ref() targets exist
    ents = (pkg["yaml"].get("data/entities.yaml") or {}).get("entities", {}) or {}
    for ename, ent in ents.items():
        for fname, f in (ent.get("fields") or {}).items():
            t = str((f or {}).get("type", ""))
            m = re.match(r"ref\((\w+)\)", t)
            if m:
                st = "pass" if m.group(1) in ents else "fail"
                res.add("L1", f"ref:{ename}.{fname}->{m.group(1)}", st)

    # migrations well-formed
    for rel, doc in pkg["yaml"].items():
        if rel.startswith("data/migrations/"):
            ok = isinstance(doc, dict) and doc.get("id") and doc.get("up")
            res.add("L1", f"migration:{rel}", "pass" if ok else "fail")

    # invariant probes reference real paths
    for inv in pkg.get("invariants", []):
        chk = inv.get("check")
        if chk:
            p = (chk.get("request") or {}).get("path", "").split("?", 1)[0]
            # /__test/* are TEST_HOOKS surfaces (proposal 0002), not part of the
            # app's OpenAPI contract — exempt from the interface-coherence check.
            if p.startswith("/__test/"):
                res.add("L1", f"probe->path:{inv.get('id')}", "pass", f"{p} (test-hook, exempt)")
            else:
                hit = p in paths or any(
                    re.fullmatch(re.sub(r"\{[^}]+\}", "[^/]+", k), p) for k in paths)
                res.add("L1", f"probe->path:{inv.get('id')}", "pass" if hit else "fail", p)

# ------------------------------------------------------------------- L2 ------

def subst(obj, fixtures):
    if isinstance(obj, str):
        def rep(m):
            cur = fixtures
            for part in m.group(1).split("."):
                cur = (cur or {}).get(part)
            return str(cur) if cur is not None else m.group(0)
        return re.sub(r"\$fixture\.([\w.]+)", rep, obj)
    if isinstance(obj, dict):
        return {k: subst(v, fixtures) for k, v in obj.items()}
    if isinstance(obj, list):
        return [subst(v, fixtures) for v in obj]
    return obj

def http_call(base, reqspec, timeout=30):
    url = base.rstrip("/") + reqspec.get("path", "/")
    method = reqspec.get("method", "GET").upper()
    body = reqspec.get("body")
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    for k, v in (reqspec.get("headers") or {}).items():
        req.add_header(k, v)
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
            raw = r.read().decode()
            return r.status, raw
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace")

def schema_check(schema, value, path="$"):
    """Minimal JSON-Schema subset: type, required, properties, items, min/maxItems."""
    errs = []
    t = schema.get("type")
    types = t if isinstance(t, list) else ([t] if t else [])
    if types:
        pymap = {"object": dict, "array": list, "string": str,
                 "integer": int, "number": (int, float), "boolean": bool}
        allowed = tuple(pymap[x] for x in types if x in pymap)
        null_ok = "null" in types
        if value is None:
            if not null_ok:
                errs.append(f"{path}: null not allowed")
        elif allowed and not isinstance(value, allowed):
            errs.append(f"{path}: expected {types}, got {type(value).__name__}")
        if "integer" in types and isinstance(value, bool):
            errs.append(f"{path}: bool where integer expected")
    if isinstance(value, dict):
        for r in schema.get("required", []):
            if r not in value:
                errs.append(f"{path}: missing required '{r}'")
        for k, sub in (schema.get("properties") or {}).items():
            if k in value:
                errs += schema_check(sub, value[k], f"{path}.{k}")
    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            errs.append(f"{path}: {len(value)} items < minItems {schema['minItems']}")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errs.append(f"{path}: {len(value)} items > maxItems {schema['maxItems']}")
        sub = schema.get("items")
        if sub:
            for i, v in enumerate(value):
                errs += schema_check(sub, v, f"{path}[{i}]")
    return errs

def resolve_response_schema(pkg, ref, status):
    """ref like 'interface/api.openapi.yaml#/paths/~1api~1x' -> schema for status."""
    file_part, _, frag = ref.partition("#")
    node = pkg["yaml"].get(file_part) or {}
    for part in frag.strip("/").split("/"):
        part = part.replace("~1", "/")
        if isinstance(node, dict) and part in node:
            node = node[part]
        else:
            return None
    # descend post -> responses -> status -> content -> application/json -> schema
    for k in ("post", "get", "put", "delete"):
        if k in node:
            node = node[k]
            break
    try:
        return node["responses"][str(status)]["content"]["application/json"]["schema"]
    except (KeyError, TypeError):
        return None

def contains(expected, actual):
    if isinstance(expected, dict) and isinstance(actual, dict):
        return all(k in actual and contains(v, actual[k]) for k, v in expected.items())
    return expected == actual

# --------------------------------------------------------------- DB adapter --

class DBAdapter:
    """Executes scalar queries against the app's datastore for db_checks.

    command mode (zero-dependency): a shell template where {query} becomes a
    single argv element, e.g.
        command: "docker exec roundtrip-pg psql -U postgres -d dandi -tAc {query}"
    psycopg mode: dsn string; requires psycopg or psycopg2 importable.
    """

    def __init__(self, cfg):
        self.cfg = cfg or {}
        self.mode = self.cfg.get("mode")

    def available(self):
        return self.mode in ("command", "psycopg")

    def scalar(self, query):
        if self.mode == "command":
            argv = []
            for tok in shlex.split(self.cfg["command"]):
                argv.append(query if tok == "{query}" else tok.replace("{query}", query))
            out = subprocess.run(argv, capture_output=True, text=True, timeout=30)
            if out.returncode != 0:
                raise RuntimeError(f"db command failed: {out.stderr.strip()[:120]}")
            return out.stdout.strip()
        if self.mode == "psycopg":
            try:
                import psycopg
                conn = psycopg.connect(self.cfg["dsn"])
            except ImportError:
                import psycopg2 as psycopg
                conn = psycopg.connect(self.cfg["dsn"])
            with conn, conn.cursor() as cur:
                cur.execute(query)
                row = cur.fetchone()
            conn.close()
            return "" if row is None else str(row[0])
        raise RuntimeError("no db adapter configured")

class DBRegistry:
    """v0.2.1: named adapters for multi-datastore apps.

    fixtures `db:` may be either a single adapter config (has a `mode` key —
    back-compat, registered as the default) or a map of store-name -> adapter
    config. db_checks select a store via their `store:` key; checks without
    one use the default (only valid when a single adapter is configured).
    """

    def __init__(self, cfg):
        self.adapters = {}
        cfg = cfg or {}
        if "mode" in cfg:                       # single, unnamed (v0.2 style)
            self.adapters["__default__"] = DBAdapter(cfg)
        else:
            for name, sub in cfg.items():
                if isinstance(sub, dict):
                    self.adapters[name] = DBAdapter(sub)

    def resolve(self, store):
        if store:
            return self.adapters.get(store)     # None -> unknown store name
        if "__default__" in self.adapters:
            return self.adapters["__default__"]
        if len(self.adapters) == 1:
            return next(iter(self.adapters.values()))
        return None                             # ambiguous: multiple stores, no store: key

def eval_db_checks(db, checks, pre_values, res, gate_name):
    for i, chk in enumerate(checks):
        name = chk.get("name", f"db_check[{i}]")
        sub = f"{gate_name}:db:{name}"
        adapter = db.resolve(chk.get("store")) if db else None
        if adapter is None and chk.get("store"):
            res.add("L2", sub, "fail", f"unknown store {chk['store']!r} (not in fixtures db map)")
            continue
        if not (adapter and adapter.available()):
            res.add("L2", sub, "skip", "no db adapter configured for this check")
            continue
        try:
            post = adapter.scalar(chk["query"])
        except Exception as e:
            res.add("L2", sub, "fail", str(e))
            continue
        if "delta" in chk:
            pre = pre_values.get(i)
            if pre is None:
                res.add("L2", sub, "fail", "pre-value query failed")
                continue
            try:
                actual = float(post) - float(pre)
            except ValueError:
                res.add("L2", sub, "fail", f"non-numeric delta operands: {pre!r} -> {post!r}")
                continue
            ok = actual == float(chk["delta"])
            res.add("L2", sub, "pass" if ok else "fail",
                    "" if ok else f"delta {actual:+g} != {chk['delta']:+g} ({pre} -> {post})")
        elif "equals" in chk:
            ok = str(post).strip() == str(chk["equals"]).strip()
            res.add("L2", sub, "pass" if ok else "fail",
                    "" if ok else f"got {post!r}, expected {chk['equals']!r}")
        else:
            res.add("L2", sub, "skip", "db_check has neither delta nor equals")

def run_gate(pkg, base, gate_name, spec, fixtures, res, db=None):
    spec = subst(spec, fixtures)
    reqspec = spec.get("request")
    expect = spec.get("expect") or {}
    if not reqspec:
        res.add("L2", gate_name, "skip", "no request probe defined")
        return
    if "$fixture." in json.dumps(reqspec):
        res.add("L2", gate_name, "skip", "unresolved fixture reference")
        return
    # capture pre-values for delta-style db_checks BEFORE the request fires
    db_checks = (spec.get("expect") or {}).get("db_checks") or []
    pre_values = {}
    for i, chk in enumerate(db_checks):
        adapter = db.resolve(chk.get("store")) if db else None
        if "delta" in chk and adapter and adapter.available():
            try:
                pre_values[i] = adapter.scalar(chk["query"])
            except Exception:
                pre_values[i] = None
    try:
        status, raw = http_call(base, reqspec)
    except Exception as e:
        res.add("L2", gate_name, "fail", f"transport: {e}")
        return
    fails = []
    if "status" in expect and status != expect["status"]:
        fails.append(f"status {status} != {expect['status']}")
    body = None
    if raw:
        try:
            body = json.loads(raw)
        except json.JSONDecodeError:
            body = None
    if "body_contains" in expect:
        if body is None or not contains(expect["body_contains"], body):
            fails.append(f"body_contains mismatch (got: {str(raw)[:120]})")
    if "body_not_contains" in expect:
        needles = expect["body_not_contains"]
        needles = needles if isinstance(needles, list) else [needles]
        for needle in needles:
            if str(needle) in (raw or ""):
                fails.append(f"body_not_contains violated: {needle!r} present in response")
    if "body_schema" in expect:
        if body is None:
            fails.append("non-JSON body for inline schema check")
        else:
            fails += schema_check(expect["body_schema"], body)
    if "body_schema_ref" in expect:
        schema = resolve_response_schema(pkg, expect["body_schema_ref"], expect.get("status", status))
        if schema is None:
            fails.append("schema_ref unresolvable at runtime")
        elif body is None:
            fails.append("non-JSON body for schema check")
        else:
            fails += schema_check(schema, body)
    if expect.get("side_effects"):
        res.add("L2", gate_name + ":side_effects", "skip",
                "prose side_effects are documentation; use db_checks for executable form")
    res.add("L2", gate_name, "fail" if fails else "pass", "; ".join(fails))
    eval_db_checks(db, db_checks, pre_values, res, gate_name)

def check_l2(pkg, base, fixtures, res, db=None):
    for case in pkg["goldens"]:
        run_gate(pkg, base, f"golden:{case.get('name','?')}", case, fixtures, res, db)
    for inv in pkg.get("invariants", []):
        iid = inv.get("id", "?")
        if inv.get("check"):
            run_gate(pkg, base, f"invariant:{iid}", inv["check"], fixtures, res, db)
        else:
            res.add("L2", f"invariant:{iid}", "skip", "prose-only invariant (no check probe)")
    for rel, _ in pkg.get("features", []):
        res.add("L2", f"scenario:{rel}", "skip", "scenario runner not implemented in v0")

# ------------------------------------------------------------------ main -----

def print_report(res):
    s = res.summary()
    print("\n== intentpkg conformance report ==")
    for lv in ("L0", "L1", "L2"):
        print(f"  {lv}: {s['levels'][lv]}")
    print(f"  gates: {s['gates']['pass']} pass / {s['gates']['fail']} fail / {s['gates']['skip']} skip")
    if s["fidelity"] is not None:
        print(f"  fidelity (pass / executed): {s['fidelity']}")
    if s.get("l2_coverage") is not None:
        print(f"  L2 probe coverage (executed / declared): {s['l2_coverage']}")
    print(f"  {s['coverage_note']}")
    fails = [c for c in res.checks if c["status"] == "fail"]
    if fails:
        print("\n  failures:")
        for c in fails:
            print(f"    [{c['level']}] {c['gate']}: {c['detail']}")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["validate", "verify"])
    ap.add_argument("package")
    ap.add_argument("--base-url")
    ap.add_argument("--fixtures")
    ap.add_argument("--json", dest="json_out")
    args = ap.parse_args()

    pkg_dir = Path(args.package)
    if not pkg_dir.is_dir():
        print(f"not a directory: {pkg_dir}", file=sys.stderr)
        sys.exit(2)

    res = Result()
    pkg = load_package(pkg_dir, res)
    if pkg is None:
        print_report(res)
        sys.exit(2)
    check_l0(pkg, res)
    check_l1(pkg, res)

    if args.command == "verify":
        if not args.base_url:
            print("verify requires --base-url", file=sys.stderr)
            sys.exit(2)
        fixtures = {}
        if args.fixtures:
            fixtures = load_yaml(Path(args.fixtures)) or {}
        db = DBRegistry(fixtures.get("db"))
        check_l2(pkg, args.base_url, fixtures.get("fixture", fixtures), res, db)

    print_report(res)
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(
            {"summary": res.summary(), "checks": res.checks}, indent=2))
        print(f"\n  json report -> {args.json_out}")
    sys.exit(0 if all(c["status"] != "fail" for c in res.checks) else 1)

if __name__ == "__main__":
    main()
