# LDM Worked Examples

Six messages covering the formatting variants that a production parser has to survive. Each is
followed by a field-by-field reading and the validation arithmetic.

> **All identifiers in these examples are synthetic**, and the messages themselves were
> constructed for this document rather than taken from any published source. Airline
> designators, registrations and load figures are chosen to illustrate formatting variants
> and to be internally consistent. They do not correspond to any real flight, operator or
> aircraft. Destination codes are real airport codes used purely as neutral placeholders.

---

## Example 1 — Single-class narrowbody, four-value passenger form

```
LDM
ZZ412/24.XYABC.Y189.3/5
-FRA.41/28/2/2.T1340.4/1340.PAX/71
.B/1340
SI
41/1320.42/20
BPCS/82.41/80.42/2
TRA BAGS LDD H41 DOORSIDE
1PCS BC (PRIO) LOADED IN H42
```

**Reading**

| Field | Value |
|-------|-------|
| Flight | ZZ412, day 24 |
| Registration | XYABC |
| Version | `Y189` — single class, 189 economy seats |
| Crew | 3 cockpit, 5 cabin (two-part form) |
| Destination | FRA |
| Passengers | 41 male, 28 female, 2 children, 2 infants |
| Total deadload | 1,340 kg |
| Compartments | hold 4: 1,340 kg |
| PAX per class | 71 — single value, single cabin |
| Load category | `.B/1340` on a continuation line — baggage, **not** a compartment |

**Validation**

- Adults = 41 + 28 = 69; seated PAX = 69 + 2 children = **71** — matches `.PAX/71` ✓
- Infants (2) correctly excluded from PAX; Souls on Board = 71 + 2 + 8 crew = 81
- Compartment total 1,340 = `.T1340` ✓
- SI holds: 1,320 + 20 = 1,340 ✓
- Bag pieces: 80 + 2 = 82 = `BPCS/82` ✓

**Two parser traps.** First, `.B/1340` is on its own line but belongs to the FRA block — a parser
that treats every line break as a block boundary loses it entirely. Second, once recovered, it is
easily misread as a compartment named `B`, which doubles the load to 2,680 against a stated total
of 1,340. It is a load-category breakdown: 1,340 kg of baggage, restating the total rather than
adding to it.

---

## Example 2 — Multi-class, three-value passenger form, multiple compartments

```
LDM
QQ702/24.XYBCD.C12Y162.2/4
-VIE.158/6/3.T5820.1/1210.2/840.3/2930.4/840.PAX/12/152
SI VIE B/5820.C/0.M/0.E/0
```

**Reading**

| Field | Value |
|-------|-------|
| Version | `C12Y162` — 12 business + 162 economy = 174 seats |
| Crew | 2 cockpit, 4 cabin |
| Passengers | 158 adults, 6 children, 3 infants (three-value form) |
| Compartments | 1: 1,210 / 2: 840 / 3: 2,930 / 4: 840 |
| PAX per class | 12 business + 152 economy |
| SI | destination-level B/C/M/E breakdown |

**Validation**

- Seated PAX = 158 + 6 = **164**; `.PAX/12/152` = 164 ✓
- Compartments 1,210 + 840 + 2,930 + 840 = 5,820 = `.T5820` ✓
- SI: B/5820 + C/0 + M/0 + E/0 = 5,820 ✓ — the entire deadload is baggage, no cargo or mail

**Note:** the three-value form gives no gender split. `male` and `female` are genuinely unknown here,
not zero. Storing them as `0` rather than `null` produces false precision downstream.

---

## Example 3 — Aircraft type as version, alpha compartments, trailing slash

```
LDM
XX0957/24.XYCDE.B772.3/9
-LHR.228/19/4/.T9974.AB/582/A2/532/A1/2915/F2/4202/F1/1743
.PAX/33/26/192
SI LHR B/4001.C/5731.M/242
```

**Reading**

| Field | Value |
|-------|-------|
| Version | `B772` — **aircraft type, no seat information at all** |
| Crew | 3 cockpit, 9 cabin — widebody |
| Passengers | 228 male, 19 female, 4 children, infant field **empty** |
| Compartments | AB: 582 / A2: 532 / A1: 2,915 / F2: 4,202 / F1: 1,743 |
| PAX per class | 33 first + 26 business + 192 economy |

**Validation**

- Seated PAX = 228 + 19 + 4 = **251**; `.PAX/33/26/192` = 251 ✓
- Compartments 582 + 532 + 2,915 + 4,202 + 1,743 = 9,974 = `.T9974` ✓
- SI: 4,001 + 5,731 + 242 = 9,974 ✓ — mixed load, cargo exceeds baggage

**Two parser traps in one line.** First, `228/19/4/` has four separators but three values — count
values, not separators, and treat the empty infant field as unknown rather than zero. Second, the
compartment list is joined with `/` throughout (`AB/582/A2/532/...`) rather than `.`, so the usual
full-stop split yields one giant token. Pair the tokens two at a time after splitting on both
delimiters.

---

## Example 4 — Numeric version, many compartments across continuation lines

```
LDM
YY847/24.XYDEF.50/24/202.3/10
-AMS.246/0/2.T9840
.001/930.003/945.007/951.009/958.013/1220
.015/1600.023/348.024/268.025/715.026/791
.030/416.031/731.032/267
.PAX/48/24/174
```

**Reading**

| Field | Value |
|-------|-------|
| Version | `50/24/202` — seats per class, no class letters |
| Crew | 3 cockpit, 10 cabin |
| Passengers | 246 adults, 0 children, 2 infants |
| Compartments | 13 positions with three-digit IDs, spanning three lines |
| PAX per class | 48 + 24 + 174 |
| SI | absent |

**Validation**

- Seated PAX = 246 + 0 = **246**; `.PAX/48/24/174` = 246 ✓
- Compartment sum = 9,840 = `.T9840` ✓

**Parser trap:** `.T9840` ends the first line and the compartment list begins on the next. Both belong
to the AMS block, and `.PAX/` arrives four lines later. Block scope is defined by the next `-` or `SI`,
never by line breaks. Note also that the version field `50/24/202` contains slashes — if you split the
flight record on `/` you will destroy it.

---

## Example 5 — Gender-split crew, cabin baggage, special loads, PAD

```
LDM
WW187/24.XYEFG.J12Y206.2/0/5
-CDG.118/74/8/0.0.T988.1/352.3/480.4/156.PAX/12/188.JMP/0.CRW/0
.PAD/0/0.AVI/4/14.HEA/1/106
SI CDG FRE 352 POS 0 BAG 636 TRA 0
POS41/ 01 AVI POS42/ 10 BAG PRIORITY + 02 BAG CONEXION
```

**Reading**

| Field | Value |
|-------|-------|
| Version | `J12Y206` — 12 premium + 206 economy |
| Crew | 2 cockpit, **0 male cabin, 5 female cabin** (three-part form) |
| Passengers | 118 male, 74 female, 8 children, 0 infants |
| Cabin baggage | `.0` — the bare zero between passengers and `.T` |
| Compartments | 1: 352 / 3: 480 / 4: 156 |
| Special loads | AVI 4 pieces / 14 kg; HEA 1 piece / 106 kg |
| JMP / CRW | 0 jump-seat occupants, 0 extra crew |
| PAD | 0 / 0 per class |

**Validation**

- Seated PAX = 118 + 74 + 8 = **200**; `.PAX/12/188` = 200 ✓
- Compartments 352 + 480 + 156 = 988 = `.T988` ✓
- SI: FRE 352 + BAG 636 = 988 ✓

**Parser traps.** The crew `2/0/5` has a legitimate zero in the male-cabin position — total cabin crew
is 5, not a parse error. The lone `.0` after the passenger array is the unlabelled cabin baggage weight; it
carries no prefix and is distinguishable only by position. And the block wraps mid-element list, with
`.PAD` opening the continuation line.

---

## Example 6 — Minimal message, no SI

```
LDM
VV7731/24.XYFGH.B40/320.2/2/4
-ZRH.61/77/17/2.T1110.1/1110.PAX/155.PAD/155
```

**Reading**

| Field | Value |
|-------|-------|
| Version | `B40/320` — carrier-internal variant code, not machine-interpretable |
| Crew | 2 cockpit, 2 male cabin, 4 female cabin |
| Passengers | 61 male, 77 female, 17 children, 2 infants |
| PAD | 155 — every passenger terminates at this destination |

**Validation**

- Seated PAX = 61 + 77 + 17 = **155**; `.PAX/155` ✓
- Compartment 1,110 = `.T1110` ✓

**Note:** SI is optional and genuinely absent here. A pipeline that requires SI to extract the
baggage/cargo/mail split will produce nothing for this flight — the only available figure is the
1,110 kg total deadload. Design the data model so that "breakdown unavailable" is representable
rather than implicitly zero.

---

## Variant summary

| Variant | Example | What it breaks |
|---------|---------|----------------|
| Version = seat map | 1, 2, 5 | — baseline |
| Version = aircraft type | 3 | capacity derivation from the version field |
| Version = slash-delimited counts | 4 | splitting the flight record on `/` |
| Version = carrier-internal code | 6 | any semantic interpretation at all |
| Crew two-part | 1, 2 | — baseline |
| Crew three-part with zero | 5, 6 | zero-as-missing assumptions |
| PAX three-value A/C/I | 2, 4 | gender fields recorded as 0 instead of null |
| PAX four-value M/F/C/I | 1, 5, 6 | — baseline |
| PAX four-value, empty infant | 3 | counting separators instead of values |
| Compartments `.`-joined | 1, 2, 4, 5, 6 | — baseline |
| Compartments `/`-joined | 3 | full-stop tokenisation |
| Compartments across lines | 4 | line-break block boundaries |
| SI hold-level + BPCS | 1 | — |
| SI B/C/M/E | 2, 3 | — |
| SI labelled free text | 5 | strict pattern matching |
| SI absent | 4, 6 | breakdown assumed mandatory |
