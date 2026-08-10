#!/usr/bin/env python3
"""Summarise benchmark results with per-repeat variance and per-variant breakdown."""

import json
import statistics
import sys
from collections import defaultdict

GROUPS = ["flight", "pax", "load", "compartments", "classes", "si"]
LABELS = {
    "flight": "Flight record",
    "pax": "Passenger counts",
    "load": "Deadload / weights",
    "compartments": "Compartment map",
    "classes": "PAX class array",
    "si": "SI breakdown",
}


def acc(records, group=None):
    hit = tot = 0
    for r in records:
        gs = r["groups"]
        keys = [group] if group else GROUPS
        for k in keys:
            hit += gs[k][0]
            tot += gs[k][1]
    return hit / tot if tot else float("nan")


def per_rep(records, group=None):
    by_rep = defaultdict(list)
    for r in records:
        by_rep[r["rep"]].append(r)
    return [acc(v, group) for v in by_rep.values()]


def fmt(vals):
    m = statistics.mean(vals)
    s = statistics.stdev(vals) if len(vals) > 1 else 0.0
    return f"{m:6.1%} ± {s:.1%}"


def main(path):
    data = json.load(open(path))
    recs = data["records"]
    arms = {a: [r for r in recs if r["arm"] == a] for a in ("baseline", "skill")}

    print(f"\nModel: {data['model']}   cases: {data['n_cases']}   "
          f"repeats: {data['repeats']}\n")

    print(f"{'':24s} {'baseline':>18s} {'+ skill':>18s} {'Δ':>8s}")
    print("-" * 72)
    for g in GROUPS:
        b, s = per_rep(arms["baseline"], g), per_rep(arms["skill"], g)
        d = statistics.mean(s) - statistics.mean(b)
        print(f"{LABELS[g]:24s} {fmt(b):>18s} {fmt(s):>18s} {d*100:+6.1f}pp")
    print("-" * 72)
    b, s = per_rep(arms["baseline"]), per_rep(arms["skill"])
    d = statistics.mean(s) - statistics.mean(b)
    print(f"{'OVERALL':24s} {fmt(b):>18s} {fmt(s):>18s} {d*100:+6.1f}pp")

    print("\nOutput validity (parseable JSON matching schema)")
    for a, rs in arms.items():
        v = sum(r["valid_json"] for r in rs) / len(rs)
        print(f"  {a:9s} {v:6.1%}")

    print("\nCritical errors (rate per response)")
    tags = sorted({t for rs in arms.values() for r in rs for t in r["critical"]})
    for t in tags:
        row = [sum(t in r["critical"] for r in arms[a]) / len(arms[a])
               for a in ("baseline", "skill")]
        print(f"  {t:34s} baseline {row[0]:6.1%}   skill {row[1]:6.1%}")

    print("\nBy variant axis (overall field accuracy)")
    axes = defaultdict(lambda: defaultdict(list))
    for a, rs in arms.items():
        for r in rs:
            for k, v in r["axes"].items():
                if not k.startswith("_"):
                    axes[f"{k}={v}"][a].append(r)
    print(f"{'':34s} {'baseline':>10s} {'+ skill':>10s} {'Δ':>9s}")
    for key in sorted(axes):
        ab, asx = acc(axes[key]["baseline"]), acc(axes[key]["skill"])
        print(f"  {key:32s} {ab:9.1%} {asx:9.1%} {(asx-ab)*100:+8.1f}pp")
    print()


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "results.json")
