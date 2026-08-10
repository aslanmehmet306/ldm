#!/usr/bin/env python3
"""
Generate a synthetic LDM benchmark test set.

Messages are rendered FROM a known ground truth, so the gold answer is exact by
construction rather than by hand-annotation. The variant axes are sampled to
cover the formatting space documented in the ldm-message-parsing skill.

Output: cases.jsonl  — one {"id", "raw", "gold", "axes"} object per line.
"""

import json
import random
import argparse

AIRLINES = ["ZZ", "QQ", "XX", "YY", "WW", "VV", "UU", "TT", "RR", "NN"]
DESTS = ["FRA", "VIE", "LHR", "AMS", "CDG", "ZRH", "MAD", "CPH", "OSL", "HEL",
         "BRU", "LIS", "DUB", "WAW", "PRG"]

VERSION_STYLES = ["seatmap_single", "seatmap_multi", "aircraft_type",
                  "slash_counts", "carrier_code"]
CREW_SHAPES = ["two_part", "three_part"]
PAX_FORMS = ["aci", "mfci", "mfci_empty_infant"]
COMP_JOINS = ["dot", "slash"]
SI_PATTERNS = ["none", "bcme", "hold_bpcs", "freetext"]


def make_registration(rng):
    return "XY" + "".join(rng.choice("ABCDEFGHJKLMNPRSTUVWXYZ") for _ in range(3))


def make_version(rng, style):
    if style == "seatmap_single":
        return f"Y{rng.choice([150, 180, 186, 189, 195])}"
    if style == "seatmap_multi":
        c = rng.choice([8, 12, 16, 20])
        y = rng.choice([120, 138, 156, 162, 174])
        return f"{rng.choice('CJ')}{c}Y{y}"
    if style == "aircraft_type":
        return rng.choice(["B772", "B788", "A333", "A320", "A21N", "B38M"])
    if style == "slash_counts":
        return f"{rng.choice([30,40,50])}/{rng.choice([18,24,28])}/{rng.choice([180,202,220])}"
    return f"B{rng.choice([38,40,44])}/{rng.choice([320,321,738])}"


def make_crew(rng, shape):
    cockpit = rng.choice([2, 2, 2, 3])
    if shape == "two_part":
        cabin = rng.choice([4, 5, 6, 8, 9, 10])
        return f"{cockpit}/{cabin}", cockpit, cabin, None, None
    male = rng.choice([0, 0, 1, 2, 3])
    female = rng.choice([2, 3, 4, 5, 6])
    return f"{cockpit}/{male}/{female}", cockpit, male + female, male, female


def split_into(rng, total, parts):
    """Split `total` into `parts` non-negative ints that sum exactly to total."""
    if parts == 1:
        return [total]
    cuts = sorted(rng.randint(0, total) for _ in range(parts - 1))
    out, prev = [], 0
    for c in cuts:
        out.append(c - prev)
        prev = c
    out.append(total - prev)
    return out


ID_POOLS = {
    "single_digit": ["1", "2", "3", "4", "5"],
    "three_digit": ["001", "003", "007", "009", "013", "015", "023", "024",
                    "025", "026", "030", "031", "032", "033", "041", "042"],
    "alpha": ["AB", "A1", "A2", "A3", "F1", "F2", "F3", "FA", "FB", "FC"],
}


def make_compartments(rng, total, n):
    styles = [s for s, pool in ID_POOLS.items() if len(pool) >= n]
    ids_style = rng.choice(styles)
    ids = rng.sample(ID_POOLS[ids_style], n)
    weights = split_into(rng, total, n)
    # avoid zero-weight compartments: rebalance
    weights = [max(1, w) for w in weights]
    drift = sum(weights) - total
    weights[0] -= drift
    if weights[0] < 1:
        return make_compartments(rng, total, n)
    return list(zip(ids, weights))


def build_destination(rng, axes):
    dest = axes["_dest"]
    pax_form = axes["pax_form"]

    child = rng.choice([0, 0, 1, 2, 3, 4, 8, 17])
    infant = rng.choice([0, 0, 1, 2, 3, 4])

    if pax_form == "aci":
        adult = rng.randint(40, 260)
        male = female = None
        pax_field = f"{adult}/{child}/{infant}"
        infant_gold = infant
    else:
        male = rng.randint(20, 160)
        female = rng.randint(15, 120)
        adult = male + female
        if pax_form == "mfci_empty_infant":
            pax_field = f"{male}/{female}/{child}/"
            infant_gold = None
        else:
            pax_field = f"{male}/{female}/{child}/{infant}"
            infant_gold = infant

    pax_seated = adult + child

    total_deadload = rng.randint(400, 11000)
    n_comp = rng.choice([1, 1, 2, 3, 4, 5, 8, 13])
    comps = make_compartments(rng, total_deadload, n_comp)

    n_class = 1 if axes["version_style"] == "seatmap_single" else rng.choice([1, 2, 2, 3])
    pax_classes = split_into(rng, pax_seated, n_class)
    if any(v < 0 for v in pax_classes):
        pax_classes = [pax_seated] + [0] * (n_class - 1)

    cabin_bag = rng.choice([None, None, 0, rng.randint(50, 400)])
    pad = rng.choice([None, None, [0], [0, 0], [rng.randint(0, 5)]])

    # ---- render ----
    seg = [f"-{dest}", pax_field]
    if cabin_bag is not None:
        seg.append(str(cabin_bag))
    seg.append(f"T{total_deadload}")
    line = ".".join(seg)

    if axes["comp_join"] == "slash":
        comp_str = "." + "/".join(f"{i}/{w}" for i, w in comps)
    else:
        comp_str = "".join(f".{i}/{w}" for i, w in comps)
    line += comp_str
    line += ".PAX/" + "/".join(str(v) for v in pax_classes)
    if pad is not None:
        line += ".PAD/" + "/".join(str(v) for v in pad)

    gold = {
        "destination": dest,
        "male": male,
        "female": female,
        "adult": adult,
        "child": child,
        "infant": infant_gold,
        "paxSeated": pax_seated,
        "cabinBaggageWeight": cabin_bag,
        "totalDeadload": total_deadload,
        "compartments": {i: w for i, w in comps},
        "paxByClass": pax_classes,
        "padByClass": pad,
    }
    return line, gold


def render_si(rng, pattern, dests_gold):
    if pattern == "none":
        return [], {}
    d = dests_gold[0]
    total = d["totalDeadload"]
    if pattern == "bcme":
        bag = int(total * rng.uniform(0.4, 1.0))
        cargo = total - bag
        return ([f"SI {d['destination']} B/{bag}.C/{cargo}.M/0.E/0"],
                {"baggageWeight": bag, "cargoWeight": cargo, "mailWeight": 0})
    if pattern == "hold_bpcs":
        holds = list(d["compartments"].items())[:2]
        if len(holds) < 2:
            holds = holds * 2
        h1, h2 = holds[0], holds[1]
        w2 = min(h2[1], rng.randint(5, 60))
        w1 = total - w2
        p1, p2 = rng.randint(40, 90), rng.randint(1, 5)
        return (["SI", f"{h1[0]}/{w1}.{h2[0]}/{w2}",
                 f"BPCS/{p1+p2}.{h1[0]}/{p1}.{h2[0]}/{p2}",
                 "TRA BAGS LDD DOORSIDE"],
                {"baggageWeight": None, "cargoWeight": None, "mailWeight": None})
    bag = int(total * rng.uniform(0.5, 0.9))
    fre = total - bag
    return ([f"SI {d['destination']} FRE {fre} POS 0 BAG {bag} TRA 0"],
            {"baggageWeight": bag, "cargoWeight": fre, "mailWeight": None})


def hard_wrap(lines, width=64):
    """Simulate telex line wrapping mid-element."""
    out = []
    for ln in lines:
        while len(ln) > width:
            out.append(ln[:width])
            ln = ln[width:]
        out.append(ln)
    return out


def make_case(rng, cid):
    axes = {
        "version_style": rng.choice(VERSION_STYLES),
        "crew_shape": rng.choice(CREW_SHAPES),
        "pax_form": rng.choice(PAX_FORMS),
        "comp_join": rng.choice(COMP_JOINS + ["dot", "dot"]),
        "si_pattern": rng.choice(SI_PATTERNS),
        "wrap": rng.choice([False, False, True]),
        "n_dest": rng.choice([1, 1, 1, 2, 3]),
    }

    airline = rng.choice(AIRLINES)
    flight_no = str(rng.randint(1, 9999))
    day = f"{rng.randint(1, 28):02d}"
    reg = make_registration(rng)
    version = make_version(rng, axes["version_style"])
    crew_str, cockpit, cabin_total, cabin_m, cabin_f = make_crew(rng, axes["crew_shape"])

    lines = ["LDM", f"{airline}{flight_no}/{day}.{reg}.{version}.{crew_str}"]

    dests = rng.sample(DESTS, axes["n_dest"])
    dest_golds = []
    for d in dests:
        a = dict(axes)
        a["_dest"] = d
        line, gold = build_destination(rng, a)
        lines.append(line)
        dest_golds.append(gold)

    si_lines, si_gold = render_si(rng, axes["si_pattern"], dest_golds)
    lines += si_lines

    if axes["wrap"]:
        lines = hard_wrap(lines)

    gold = {
        "airline": airline,
        "flightNumber": flight_no,
        "flightDay": day,
        "registration": reg,
        "aircraftVersion": version,
        "cockpitCrew": cockpit,
        "cabinCrewTotal": cabin_total,
        "maleCabinCrew": cabin_m,
        "femaleCabinCrew": cabin_f,
        "destinations": dest_golds,
        "supplementary": si_gold,
    }
    return {"id": cid, "raw": "\n".join(lines), "gold": gold, "axes": axes}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=40)
    ap.add_argument("--seed", type=int, default=20260801)
    ap.add_argument("-o", default="cases.jsonl")
    args = ap.parse_args()

    rng = random.Random(args.seed)
    with open(args.o, "w") as f:
        for i in range(args.n):
            f.write(json.dumps(make_case(rng, f"ldm-{i:03d}")) + "\n")
    print(f"wrote {args.n} cases -> {args.o} (seed={args.seed})")


if __name__ == "__main__":
    main()
