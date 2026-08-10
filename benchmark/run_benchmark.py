#!/usr/bin/env python3
"""
LDM parsing benchmark: baseline model vs. model + ldm-message-parsing skill.

Fairness design
---------------
Both arms receive the IDENTICAL output schema and the identical task instruction.
The ONLY difference is whether the skill markdown is present in the system prompt.
Withholding the schema from the baseline would measure schema-guessing, not domain
knowledge, and would produce a number that does not survive scrutiny.

Usage
-----
  export ANTHROPIC_API_KEY=sk-ant-...
  python generate_testset.py -n 40
  python run_benchmark.py --repeats 5
  python report.py results.json
"""

import argparse
import json
import os
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import anthropic

SCHEMA = """Return ONLY a JSON object, no prose, no markdown fences, in exactly this shape:

{
  "airline": str,
  "flightNumber": str,
  "flightDay": str|null,
  "registration": str,
  "aircraftVersion": str,
  "cockpitCrew": int,
  "cabinCrewTotal": int,
  "maleCabinCrew": int|null,
  "femaleCabinCrew": int|null,
  "destinations": [
    {
      "destination": str,
      "male": int|null,
      "female": int|null,
      "adult": int,
      "child": int,
      "infant": int|null,
      "paxSeated": int,
      "cabinBaggageWeight": int|null,
      "totalDeadload": int,
      "compartments": {"<designator>": int},
      "paxByClass": [int],
      "padByClass": [int]|null
    }
  ],
  "supplementary": {
    "baggageWeight": int|null,
    "cargoWeight": int|null,
    "mailWeight": int|null
  }
}

Use null for values the message does not carry. Do not invent values."""

TASK = "Parse the following IATA Type B LDM message.\n\n<message>\n{raw}\n</message>"

BASE_SYS = "You are parsing aviation industry messages into structured data.\n\n" + SCHEMA


def load_skill(skill_dir: Path) -> str:
    parts = [(skill_dir / "SKILL.md").read_text()]
    ref = skill_dir / "references"
    if ref.is_dir():
        for f in sorted(ref.glob("*.md")):
            parts.append(f"\n\n===== reference: {f.name} =====\n\n" + f.read_text())
    return "\n".join(parts)


def extract_json(text: str):
    t = text.strip()
    if t.startswith("```"):
        t = t.split("```")[1]
        if t.lstrip().startswith("json"):
            t = t.lstrip()[4:]
    t = t.strip()
    start, end = t.find("{"), t.rfind("}")
    if start == -1 or end == -1:
        return None
    try:
        return json.loads(t[start:end + 1])
    except json.JSONDecodeError:
        return None


# ---------------------------------------------------------------- scoring

FLIGHT_FIELDS = ["airline", "flightNumber", "flightDay", "registration",
                 "aircraftVersion", "cockpitCrew", "cabinCrewTotal",
                 "maleCabinCrew", "femaleCabinCrew"]
DEST_SCALARS = ["destination", "male", "female", "adult", "child", "infant",
                "paxSeated", "cabinBaggageWeight", "totalDeadload"]


def norm(v):
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return int(v)
    s = str(v).strip()
    if s == "":
        return None
    try:
        return int(s)
    except ValueError:
        return s.upper()


def score_case(pred, gold):
    """Return (per-group hit/total dict, list of critical error tags)."""
    groups = {"flight": [0, 0], "pax": [0, 0], "load": [0, 0],
              "compartments": [0, 0], "classes": [0, 0], "si": [0, 0]}
    critical = []

    if pred is None:
        for g in groups:
            groups[g][1] += 1
        return groups, ["unparseable_output"]

    for f in FLIGHT_FIELDS:
        groups["flight"][1] += 1
        if norm(pred.get(f)) == norm(gold.get(f)):
            groups["flight"][0] += 1

    gdests = gold["destinations"]
    pdests = pred.get("destinations") or []
    pmap = {}
    for d in pdests:
        if isinstance(d, dict) and d.get("destination"):
            pmap[str(d["destination"]).upper()] = d

    for gd in gdests:
        pd = pmap.get(gd["destination"], {})
        for f in DEST_SCALARS:
            grp = "pax" if f in ("male", "female", "adult", "child", "infant", "paxSeated") else "load"
            groups[grp][1] += 1
            if norm(pd.get(f)) == norm(gd.get(f)):
                groups[grp][0] += 1

        # infant leakage: PAX total silently includes infants
        gi = gd.get("infant") or 0
        if gi and norm(pd.get("paxSeated")) == gd["paxSeated"] + gi:
            critical.append("infant_in_pax")

        groups["compartments"][1] += 1
        pc = pd.get("compartments") or {}
        gc = gd["compartments"]
        if isinstance(pc, dict) and {str(k).upper(): norm(v) for k, v in pc.items()} == \
           {str(k).upper(): norm(v) for k, v in gc.items()}:
            groups["compartments"][0] += 1
        elif isinstance(pc, dict) and pc and sum(
                v for v in (norm(x) for x in pc.values()) if isinstance(v, int)
        ) == gd["totalDeadload"]:
            critical.append("compartment_ids_wrong_sum_right")

        groups["classes"][1] += 1
        ppc = pd.get("paxByClass")
        if isinstance(ppc, list) and [norm(x) for x in ppc] == gd["paxByClass"]:
            groups["classes"][0] += 1

    gsi = gold.get("supplementary") or {}
    psi = pred.get("supplementary") or {}
    for f in ("baggageWeight", "cargoWeight", "mailWeight"):
        if f in gsi:
            groups["si"][1] += 1
            if norm(psi.get(f)) == norm(gsi.get(f)):
                groups["si"][0] += 1

    return groups, critical


# ---------------------------------------------------------------- runner

def call(client, model, system, raw, max_retries=4):
    for attempt in range(max_retries):
        try:
            r = client.messages.create(
                model=model,
                max_tokens=4000,
                system=system,
                messages=[{"role": "user", "content": TASK.format(raw=raw)}],
            )
            return "".join(b.text for b in r.content if b.type == "text")
        except Exception as e:
            if attempt == max_retries - 1:
                return f"__ERROR__ {e}"
            time.sleep(2 ** attempt)
    return "__ERROR__"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", default="cases.jsonl")
    ap.add_argument("--skill", default="../skills/ldm-message-parsing")
    ap.add_argument("--model", default="claude-sonnet-4-6")
    ap.add_argument("--repeats", type=int, default=5)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("-o", default="results.json")
    args = ap.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY not set")

    client = anthropic.Anthropic()
    cases = [json.loads(l) for l in open(args.cases)]
    skill_text = load_skill(Path(args.skill))
    skill_sys = ("You are parsing aviation industry messages into structured data.\n\n"
                 "Apply the following domain knowledge:\n\n"
                 f"<domain_knowledge>\n{skill_text}\n</domain_knowledge>\n\n" + SCHEMA)

    print(f"cases={len(cases)}  repeats={args.repeats}  model={args.model}")
    print(f"skill payload = {len(skill_text):,} chars\n")

    jobs = [(arm, c, r)
            for arm, sysprompt in (("baseline", BASE_SYS), ("skill", skill_sys))
            for c in cases for r in range(args.repeats)]
    sysmap = {"baseline": BASE_SYS, "skill": skill_sys}

    records, done = [], 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(call, client, args.model, sysmap[a], c["raw"]): (a, c, r)
                for a, c, r in jobs}
        for fut in as_completed(futs):
            arm, c, rep = futs[fut]
            pred = extract_json(fut.result())
            groups, crit = score_case(pred, c["gold"])
            records.append({"arm": arm, "case": c["id"], "rep": rep,
                            "axes": c["axes"], "groups": groups,
                            "critical": crit, "valid_json": pred is not None})
            done += 1
            if done % 25 == 0:
                print(f"  {done}/{len(jobs)}")

    json.dump({"model": args.model, "repeats": args.repeats,
               "n_cases": len(cases), "records": records},
              open(args.o, "w"), indent=1)
    print(f"\nwrote {args.o}")

    # quick console summary
    for arm in ("baseline", "skill"):
        rs = [r for r in records if r["arm"] == arm]
        hit = sum(sum(g[0] for g in r["groups"].values()) for r in rs)
        tot = sum(sum(g[1] for g in r["groups"].values()) for r in rs)
        print(f"{arm:9s} overall field accuracy: {hit/tot:6.1%}")


if __name__ == "__main__":
    main()
