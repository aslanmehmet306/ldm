---
name: ldm-message-parsing
description: >
  Field-observed knowledge for parsing IATA Type B LDM (Load Distribution Message) traffic:
  how the flight record and per-destination load blocks behave in practice, the passenger
  weight-category variants, compartment designator styles, class arrays, the SI section, and
  the cross-field checks that catch a silently wrong parse.

  Use this skill when parsing or generating LDM messages, extracting passenger and load figures
  from raw Type B text, debugging LDM parse failures, designing an LDM ingestion pipeline, or
  validating parser output. Trigger on: LDM, load distribution message, total deadload,
  compartment load, PAX/PAD, deadload breakdown, SI baggage breakdown, Type B load message.
  Also trigger when a user pastes raw text beginning with "LDM".

  Scope note: this skill is implementation-agnostic and describes observed message behaviour,
  not any particular vendor's data model or codebase.
---

# LDM — Load Distribution Message Parsing

The LDM tells a downstream station what is physically on board an aircraft: passengers, baggage,
cargo and mail, broken down by destination. It is one of the oldest and most widely exchanged
IATA Type B message types, and one of the most inconsistently formatted in practice.

## What this is, and what it is not

This document records **implementation patterns and carrier-specific variations observed in live
Type B traffic** — the things that determine whether a parser survives contact with production.

It is not a specification and does not attempt to be one. The authoritative definition of the LDM
is published by IATA in the Airport Handling Manual (AHM 583), which you should consult for the
formal element definitions, mandatory/conditional status, and format notation. Nothing here
replaces that document; the two are complementary. Where this skill is useful is precisely where
a specification cannot help you — describing what carriers actually send, as opposed to what they
are supposed to send.

*Independent implementation notes. Not affiliated with or endorsed by IATA.*

## When to read the reference file

Worked examples across the formatting variants, with field-by-field analysis and the validation
arithmetic → `references/message-examples.md`

## What LDM answers, and what it doesn't

| Message | Answers the question |
|---------|---------------------|
| **LDM** | What is on board, by destination? |
| MVT | When did the aircraft move? |
| CPM | Which container is in which position? |
| UCM | Where are the ULDs, as inventory? |

LDM gives **summary totals per destination**. CPM gives **physical positions**. A system that needs
per-container detail cannot substitute LDM for CPM, and a system that needs totals should not try
to reconstruct them by summing CPM.

## Message shape

After the Type B envelope is stripped, the body looks like this:

```
LDM                                        ← message identifier
ZZ412/24.XYABC.Y189.3/5                    ← flight record
-FRA.41/28/2/2.T1340.4/1340.PAX/71         ← load block, repeats per destination
.B/1340                                    ← continuation of the same block
SI                                         ← supplementary information
41/1320.42/20
BPCS/82.41/80.42/2
```

Two structural facts drive parser design, and both are about transmission rather than format:

1. **A logical block can span multiple physical lines.** Line breaks are inserted by transmission
   systems at fixed column widths, frequently mid-element. A destination block continues until the
   next line starting with `-` or `SI`. Normalise line breaks *before* tokenising, and join
   continuations with no separator — the break can fall inside a value.
2. **Elements are separated by full stops, but full stops also appear inside values.** `.PAX/12/155`
   is one element; `.1/1170.2/780` is two compartment elements. Splitting naively on `.` destroys
   the structure. Match element *prefixes* rather than splitting blindly.
3. **Some operators separate elements with spaces instead of full stops** — often mixed within one
   line: `.2/2105.4/5330 5/1900 PAX/323`. Treat runs of whitespace inside a load block as element
   separators, exactly like full stops; no element in a load block legitimately contains a space.
   (SI free text is different — there, spaces are just spaces.)

## The flight record

A single logical line carrying flight identity, registration, an aircraft version string, and crew
counts:

```
ZZ412/24.XYABC.Y189.3/5
```

**Airline and flight number** run together, optionally followed by the day of month. Splitting them
is ambiguous: a designator may be two or three characters and may contain a digit. A three-character
designator is all letters, so match that case first and fall back to two characters — matching
greedily in the other order turns `ZZ9194` into airline `ZZ9`, flight `194`.

**Registration** arrives with hyphens removed.

**The version string is free text in practice.** Operators fill it with at least five incompatible
things:

| Style | Example | Meaning |
|-------|---------|---------|
| Single-class seat count | `Y189` | 189 economy seats |
| Multi-class seat map | `C12Y162` | 12 business + 162 economy |
| Alternate class letters | `J12Y206` | 12 premium + 206 economy |
| Aircraft type code | `B772` | Boeing 777-200, no seat information at all |
| Slash-delimited counts | `50/24/202` | seats per class, no class letters |
| Carrier-internal variant | `B40/320` | not machine-interpretable |

**Do not build logic that derives seat capacity from this field.** Treat it as an opaque string,
store it verbatim, and enrich capacity from a fleet or registration master instead. Truncating it
silently corrupts the longer forms — allow generous length.

**Crew counts come in two shapes**, distinguished only by how many slash-separated parts follow:

| Shape | Reading | Example |
|-------|---------|---------|
| Two parts | cockpit / total cabin | `3/5` |
| Three parts | cockpit / male cabin / female cabin | `2/2/4` |

Detect by counting parts, not by position. With three parts, total cabin crew is the sum of the
last two — and one of them is legitimately `0` for some operators (`2/0/5`), which must not be read
as a missing field.

## Load blocks, per destination

Each block opens with a hyphen and a three-letter destination code on a new line. `NIL` means no
traffic load to that destination — the block still exists and still counts as a leg.

### Passenger counts — the most variable element

Two forms, distinguished only by how many slash-separated values follow:

**Three values — adults / children / infants**
```
158/6/3
```

**Four values — males / females / children / infants**
```
41/28/2/2
```

Some operators emit a **trailing slash with an empty infant field**: `228/19/4/` — four separators
but only three values. A parser that counts separators rather than non-empty values misreads this
as infants unknown, which is correct, versus crashing, which is not. Treat the empty field as
unknown, never as zero.

The weight-category split exists because load-control mass calculations use different standard
weights per category. Operators using statistical rather than segregated weights send the shorter
form — in which case the gender split is genuinely unknown, and storing it as `0` produces false
precision downstream.

### The infant rule — the most commonly mis-implemented part of LDM

**An infant does not occupy a seat.** Therefore:

```
PAX (seated)     = adults + children          ← infants EXCLUDED
Souls on Board   = adults + children + infants + crew
```

In the four-value form, `adults = males + females`.

When present, the `.PAX/` element later in the same block is the cross-check: its values must sum
to `adults + children`. Treat it as a figure to reconcile against, never as a replacement — on a
mismatch, keep both values and raise a warning. If your parsed total includes infants, it will
disagree with `.PAX/` on every message carrying an infant — a silent, systematic overcount that
surfaces downstream in billing, statistics and load-factor reporting.

If there is deadload to a destination but no passengers, the counts arrive as explicit zeros, not
omitted.

### Cabin baggage weight

An unlabelled number sitting between the passenger counts and the total deadload: `.218`. Because
it carries no prefix, it is easy to mistake for part of the passenger array. Position is the only
signal. It appears as `.0` frequently.

### Total deadload

`.T` followed by digits, in kilograms. This is the anchor value for validation: compartment loads
for the destination should sum to it, and the SI weight breakdown should also sum to it.

Some operators put a stop between the marker and the value: `.T.9335` instead of `.T9335` (the
same happens with `.TW`). A bare `T` or `TW` token followed by a number is that total. Left
unhandled, the marker is dropped and the number falls through to whatever positional rule comes
next — typically misread as the unlabelled cabin baggage weight, which is a silent wrong value
rather than a parse failure.

### Compartment loads

Repeating designator/weight pairs. Designators run one to three characters and may be numeric,
alphabetic, or mixed:

```
.4/1340                                       simple single hold
.1/1210.2/840.3/2930.4/840                    numeric holds
.AB/582/A2/532/A1/2915/F2/4202/F1/1743        alpha designators, slash-joined
.001/930.003/945.007/951                      three-digit position IDs
```

Note the third form: some operators join pairs with `/` rather than `.`, producing one long token.
Widebody operators may emit a dozen or more compartments, wrapping across several continuation
lines — which is why line normalisation has to happen first.

Compartment sums **do not always match the total**. On multi-destination flights a hold can carry
load for several destinations, and some operators report hold totals rather than per-destination
splits. Treat a mismatch as a warning, not a parse failure.

### A weight breakdown can masquerade as a compartment

Some operators append a load-category breakdown to the block, often on a continuation line:

```
-FRA.41/28/2/2.T1340.4/1340.PAX/71
.B/1340
```

`.B/1340` here is 1,340 kg of baggage — not a compartment called `B`. But it is structurally
identical to `.AB/582`: letters, slash, digits. Shape cannot separate them, and reading it as a
compartment doubles the load, producing a total that fails reconciliation for no visible reason.

Single letters `B`, `C`, `M` and `E` are also legitimate position designators on freighters
(`-GVA.B/740.F/2325.G/1874`), so they cannot simply be reserved. The workable rule is positional:
treat `B`/`C`/`M`/`E` as a category breakdown only when the total weight element and at least one
compartment have already been seen in that block. On a freighter these letters lead the block, so
they stay compartments; on a passenger flight they arrive after the real compartments, so they are
recognised as categories.

Whichever way a parser resolves it, it should record the interpretation rather than silently
choose — this is a case where a human reading the output needs to see the decision that was made.

### PAX and PAD per class

```
.PAX/71                 single value — reported seated total
.PAX/12/152             business / economy
.PAX/33/26/192          first / business / economy
```

Two or more values are an explicit per-class distribution. A **single value is the reported seated
total** — on a single-cabin aircraft this coincides with the one-class figure, but treat it as a
total to reconcile against, and do not infer a cabin layout from it (the version field is free
text and carries no reliable layout either).

Multi-value arrays run in **descending cabin priority order**, and the count is not fixed. Map
from the right: the last value is always the lowest cabin. Indexing from the left breaks whenever
an operator changes cabin configuration.

`.PAD/` follows the same shape and carries Passengers At Destination, including last-minute changes.

### Remarks and special loads

Three-letter service and special-load codes appended to the block:

```
.AVI/4/14        live animals: 4 pieces, 14 kg
.HEA/1/106       heavy piece: 1 piece, 106 kg
.JMP/0.CRW/0     jump-seat occupants, extra crew
.ELI.PER.DGR     flags with no values
```

Some codes carry values, some are bare flags, and both appear in the same message. They may also
wrap onto a continuation line, so the remarks parser must tolerate an element with zero arguments.

**A code and a compartment designator can look identical.** `AVI/4/14` is a remark; `AB/582` is a
compartment. Both are alphabetic followed by a slash and digits. The only reliable discriminator is
a known code list — the service and special-load codes are defined in AHM 510. Maintain the list
from the codes you actually encounter rather than assuming shape alone will separate them.

## Cargo-only flights

Freighters replace the passenger structure entirely: no passenger counts, and a total weight
element (`.TW`) in place of total deadload (`.T`). It may appear at the *end* of the block rather
than before the compartment list. Check for `TW` before `T` when matching, or `TW3216` parses as
`T` followed by a nonsense value. Branch on this early — a parser that assumes the passenger
structure produces empty passenger objects for every freighter rather than failing loudly.

Freighters may also carry a last-minute-change section after the supplementary information,
expressing post-message corrections as signed adjustments per destination.

## Supplementary Information

Begins with `SI`. Formally optional and informally essential — this is where the weight breakdown
that most downstream systems actually need tends to live. Four recurring patterns:

**Hold-level weights and bag piece counts**
```
SI
41/1320.42/20                    hold 41: 1,320 kg; hold 42: 20 kg
BPCS/82.41/80.42/2               82 bag pieces total; 80 in hold 41, 2 in hold 42
TRA BAGS LDD H41 DOORSIDE        free text
```

**Destination-level baggage / cargo / mail / equipment split**
```
SI FRA B/5820.C/0.M/0.E/0        kilograms
```

**Labelled free-text totals**
```
SI FRA FRE 352 POS 0 BAG 636 TRA 0
POS41/ 01 AVI POS42/ 10 BAG PRIORITY
```

**Unstructured operational notes**
```
02 WCHS PAX
1PCS WEAP LOADED IN H11
24PCS BT LOADED IN H13
```

The first two are machine-readable. The third is recoverable with tolerant keyword search. The
fourth is not structured data and should be preserved verbatim as a text field rather than
force-parsed. Do not discard it — it frequently contains the only record of special handling.

## Validation checks worth implementing

Run these after parsing; each catches a distinct class of error.

| Check | Catches |
|-------|---------|
| `.PAX/` values sum == adults + children | infant leaking into the PAX total |
| adults == males + females (four-value form) | wrong variant detected |
| compartment sum == total (single-destination only) | dropped or duplicated compartment |
| SI breakdown sum == total | misparsed SI pattern |
| `BPCS/` total == sum of per-hold piece counts | truncated continuation line |
| every block has a total weight element | block boundary detection failure |
| destination codes are valid and appear in the routing | continuation line misread as a new block |

Cross-field consistency is the only reliable way to detect a *silently* wrong parse. Type B messages
rarely fail loudly; they produce plausible numbers that are quietly incorrect.

## Analysing a raw LDM — checklist

1. Strip the Type B envelope down to the text section.
2. Normalise line breaks: force a break before every `-` block and before `SI`; join continuations
   with no separator.
3. Read the flight record: airline, flight number, day, registration, version, crew.
4. Detect crew shape by counting parts.
5. For each destination block:
   - destination code, or `NIL`
   - passenger counts — count values, detect three- vs four-value form, handle the trailing slash
   - optional unlabelled cabin baggage weight
   - total deadload, or total weight on a freighter
   - compartment pairs — tolerate `.`-joined and `/`-joined forms
   - `.PAX/` and `.PAD/` arrays — map from the right
   - remarks and special-load codes, checked against a known code list
6. Classify and parse the SI section by pattern; keep the unstructured remainder as text.
7. Run the validation checks; surface warnings rather than silently normalising.

## Implementation notes

- **Store the raw message.** Reprocessing is routine as parser coverage improves, and the original
  is the only source of truth for a disputed load figure.
- **Never truncate the version field.** Short limits corrupt multi-class configurations with no
  error.
- **Validate destination codes against the flight's actual routing**, not against a global airport
  table. A code that is well-formed but not on this routing is almost always a misparsed
  continuation line.
- **Expect duplicates.** The same LDM is frequently retransmitted. Deduplicate on message identity,
  and decide explicitly whether a later message supersedes or is rejected — silently processing
  both double-counts the load.
- **Keep units explicit.** Weights are kilograms by convention but the message does not say so.
  Carry the unit in your data model rather than assuming it downstream.
