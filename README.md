# LDM — Type B load message parsing

Implementation notes and a working parser for the **Load Distribution Message**, the IATA Type B
message that tells a downstream station what is physically on board an aircraft.

**[→ Try the parser](https://aslanmehmet306.github.io/ldm/)** — paste a real message, see it parsed
and cross-checked. Runs entirely in your browser; nothing is uploaded.

---

## Why this exists

The LDM format is specified. What carriers actually send is not.

The version field might hold a seat map, an aircraft type code, or something internal to the
carrier. The passenger element has three values on some flights and four on others, and sometimes
four separators with only three values. Compartments are usually joined with full stops and
occasionally with slashes. Transmission systems break lines at column 64, frequently in the middle
of an element. None of this is a defect — it is what live traffic looks like, and a parser either
knows about it or quietly produces wrong numbers.

This repository writes that knowledge down.

## What's here

| Path | |
|------|---|
| `skills/ldm-message-parsing/` | The knowledge, as a skill file you can hand to an AI model |
| `docs/index.html` | The same rules as a standalone browser parser — no build, no dependencies |
| `benchmark/` | Harness measuring whether the skill actually changes extraction accuracy |
| `tests/` | Parser test suite — `node --test 'tests/*.test.mjs'`, no dependencies |

## The skill

`SKILL.md` plus one reference file of worked examples. Drop the folder into wherever your tooling
looks for skills, or paste the contents into a system prompt. It covers the flight record, the
per-destination load blocks, the passenger weight-category variants, compartment designator styles,
the class arrays, the SI section, and the cross-field checks that catch a silently wrong parse.

The single most useful thing in it: **an infant does not occupy a seat.** Seated passengers are
adults plus children. Getting this wrong produces a plausible number that quietly inflates load
factor and — depending on the applicable tariff — anything billed per passenger. Where the
message carries a `.PAX/` element, it catches the error on the spot.

## The parser

`docs/index.html` is one file, ~35 KB, zero dependencies, no network calls of any kind — not even
web fonts. Open it locally or use the hosted link above.

It does two things. It parses, and then it cross-checks the message against itself: compartment
weights against total deadload, the class array against the passenger counts, the SI breakdown
against the total, bag piece counts against their per-hold sums. Where a message is ambiguous — a
weight breakdown that looks exactly like a compartment, for instance — it states which reading it
chose rather than choosing silently.

## The benchmark

Does the skill actually help, or does a capable model already handle this?

```bash
cd benchmark
pip install anthropic
export ANTHROPIC_API_KEY=...
python generate_testset.py -n 40
python run_benchmark.py --repeats 5
python report.py results.json
```

Both arms get the identical output schema and task instruction; the only difference is whether the
skill is present. Test messages are rendered *from* ground truth rather than hand-annotated, so the
gold answer is correct by construction. Every case runs multiple times and the report shows the
standard deviation, so a difference smaller than the run-to-run noise is visible as noise. See
[`benchmark/README.md`](benchmark/README.md) for the method.

## Scope

These are implementation notes, not a specification, and they are **not affiliated with or endorsed
by IATA**. They contain no element tables, format notation, or examples from any published standard;
every example message here was constructed for this repository and is synthetic. For authoritative
definitions, consult the officially licensed IATA publications — the LDM is defined in the Airport
Handling Manual. See [NOTICE.md](NOTICE.md).

The intent is to be complementary: a specification tells you what carriers are supposed to send,
these notes record what they actually send.

## Contributing

Coverage is deliberate rather than exhaustive. If you have a message this mishandles, that is the
interesting case — open an issue with the message **redacted of any real flight, registration or
operator identity**. A synthetic message that reproduces the shape is more useful than a real one.

## Licence

Documentation and skill files: CC BY 4.0. Source code: MIT. See `LICENSE` and `LICENSE-DOCS`.
