"""Command line:  python -m skygames_engine analyze --task distance a.csv b.csv -o out/"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

from . import analyze_heat, load_rules, render_heat_artifacts
from .tasks import all_tasks


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="skygames_engine")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("analyze", help="Analyze a heat")
    a.add_argument("files", nargs="+")
    a.add_argument("--task", required=True, choices=sorted(all_tasks()))
    a.add_argument("--name", default="Heat")
    a.add_argument("--rules", default=None, help="path to rules.yaml")
    a.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                   help="override a rule, e.g. --set window.top_ft=10000")
    a.add_argument("-o", "--out", default="out")
    a.add_argument("--no-png", action="store_true")
    args = ap.parse_args(argv)

    overrides: dict = {}
    for kv in args.set:
        k, v = kv.split("=", 1)
        node = overrides
        *path, leaf = k.split(".")
        for p in path:
            node = node.setdefault(p, {})
        try:
            node[leaf] = json.loads(v)      # numbers, true/false/null, lists
        except json.JSONDecodeError:
            node[leaf] = v                  # plain strings, e.g. MSL
    rules = load_rules(args.rules, overrides)

    files = []
    for p in args.files:
        with open(p, "rb") as f:
            files.append((os.path.splitext(os.path.basename(p))[0], f.read(), os.path.basename(p)))

    t0 = time.perf_counter()
    heat = analyze_heat(files, args.task, rules, args.name)
    t1 = time.perf_counter()
    arts = render_heat_artifacts(heat, include_png=not args.no_png)
    t2 = time.perf_counter()
    os.makedirs(args.out, exist_ok=True)
    for fn, b in arts.items():
        with open(os.path.join(args.out, fn), "wb") as f:
            f.write(b)

    unit = getattr(rules.tasks, args.task).unit
    print(f"{args.name} - {getattr(rules.tasks, args.task).label}  (rules {heat.rules_version}/{heat.rules_fingerprint})")
    for r in heat.ranking:
        sc = f"{r['score']:.2f} {unit}" if r["score"] is not None else f"DNF - {r['reason']}"
        flags = f"  ⚠ {'; '.join(r['quality_flags'])}" if r.get("quality_flags") else ""
        print(f"  {r['rank'] or '-':>3}  {r['flyer']:<20} {sc}{flags}")
    for j in heat.jumps:
        for w in j.warnings:
            print(f"  note [{j.flyer}]: {w}")
    print(f"analysis {1000*(t1-t0):.0f} ms, artifacts {1000*(t2-t1):.0f} ms -> {args.out}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
