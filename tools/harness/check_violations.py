#!/usr/bin/env python3
"""CI checker for the planted-violations run (tools/harness, VIOLATIONS=1).

A working UI runner must (a) fail the run, (b) catch every one of the six
planted breach categories, and (c) produce NO failure outside those
categories or their declared cascades. Exit 0 iff all three hold.

Usage: check_violations.py <violations-report.json>
"""
import json, sys

CATEGORIES = {
    "missing-anchor (login tagline)":   lambda g, d: "anchor:login.main.tagline" in g,
    "focus-order (login swapped DOM)":  lambda g, d: g.startswith("screen:login") and ":focus-order" in g,
    "reworded copy (closed banner)":    lambda g, d: "closed-banner" in g and ":copy" in g,
    "forbidden portal accent":          lambda g, d: g.startswith("portal-palette:"),
    "off-palette color (teal button)":  lambda g, d: g.startswith("palette:") or g.startswith("binding:"),
    "injected dialog":                  lambda g, d: ":no-unexpected-dialogs" in g,
}
# Declared cascades: the dismissed confirm dialog cancels the close, so later
# steps of that one flow legitimately fail downstream of the planted dialog.
CASCADES = [lambda g, d: g.startswith("flow:converse-and-close")]

def main(path):
    d = json.load(open(path))
    fails = [(c["gate"], c.get("detail", "")) for c in d["checks"] if c["status"] == "fail"]
    ok = True
    if d["summary"]["level"] != "fail":
        print("FAIL: violations run did not fail overall"); ok = False
    for name, match in CATEGORIES.items():
        if not any(match(g, det) for g, det in fails):
            print(f"FAIL: planted breach NOT caught: {name}"); ok = False
    known = list(CATEGORIES.values()) + CASCADES
    for g, det in fails:
        if not any(m(g, det) for m in known):
            print(f"FAIL: unexpected failure (false positive?): {g} — {det[:100]}"); ok = False
    n = len(fails)
    print(("OK" if ok else "BROKEN") + f": {n} failures, all six categories caught, no strays" if ok
          else f"checker verdict: BROKEN ({n} failures analyzed)")
    return 0 if ok else 1

if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
