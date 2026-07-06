#!/usr/bin/env python3
"""Validate real packages against the spec schemas. The spec must describe
the format that actually exists, or it is fiction."""
import json, sys
from pathlib import Path
import yaml
from jsonschema import Draft202012Validator, RefResolver

SDIR = Path(__file__).parent / "schemas"
schemas = {p.stem: json.loads(p.read_text()) for p in SDIR.glob("*.schema.json")}
store = {s["$id"]: s for s in schemas.values()}
# also register by bare filename for relative $refs
for p in SDIR.glob("*.schema.json"):
    store[p.name] = json.loads(p.read_text())

MAP = [
    ("manifest.yaml", "manifest"),
    ("data/entities.yaml", "entities"),
    ("behavior/invariants.yaml", "invariants"),
    ("integrations/integrations.yaml", "integrations"),
    ("fixtures.example.yaml", "fixtures"),
    ("provenance.lock", "provenance-lock"),
    ("interface/surfaces.yaml", "surfaces"),
    ("interface/unscoped-surfaces.yaml", "unscoped-surfaces"),
    ("build/constraints.yaml", "constraints"),
    ("ui/screens.yaml", "screens"),
    ("ui/tokens.yaml", "tokens"),
    ("ui/copy.yaml", "copy"),
]

fails = 0
for pkg in sys.argv[1:]:
    pkg = Path(pkg)
    print(f"── {pkg.name} ──")
    # golden files
    targets = list(MAP) + [(str(p.relative_to(pkg)), "golden-cases")
                           for p in sorted(pkg.glob("behavior/golden/*.yaml"))] \
                        + [(str(p.relative_to(pkg)), "flow")
                           for p in sorted(pkg.glob("ui/flows/*.flow.yaml"))]
    for rel, sname in targets:
        f = pkg / rel
        if not f.exists():
            continue
        doc = yaml.safe_load(f.read_text())
        schema = schemas[f"{sname}.schema"]
        resolver = RefResolver(base_uri=schema["$id"], referrer=schema, store=store)
        errs = sorted(Draft202012Validator(schema, resolver=resolver).iter_errors(doc),
                      key=lambda e: str(e.path))
        if errs:
            fails += len(errs)
            print(f"  ✗ {rel} [{sname}]")
            for e in errs[:4]:
                print(f"      {'/'.join(map(str,e.path)) or '<root>'}: {e.message[:110]}")
        else:
            print(f"  ✓ {rel} [{sname}]")
print(f"\n{'ALL VALID' if fails == 0 else f'{fails} VALIDATION ERROR(S)'}")
sys.exit(1 if fails else 0)
