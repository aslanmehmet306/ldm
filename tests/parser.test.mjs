import test from "node:test";
import assert from "node:assert/strict";
import {parseLDM, only, checkFor} from "./load-parser.mjs";

// The message these corrections were derived from. Kept verbatim.
const MSG = `LDM
ZZ412/24.XYABC.Y189.3/5
-FRA.41/28/2/2.T1340.4/1340.PAX/71
.B/1340
SI
41/1320.42/20
BPCS/82.41/80.42/2
TRA BAGS LDD H41 DOORSIDE`;

test("flight record keeps the version verbatim", () => {
  const {result} = parseLDM(MSG);
  assert.equal(result.aircraftVersion, "Y189");
  assert.equal(result.airline, "ZZ");
  assert.equal(result.flightNumber, "412");
  assert.equal(result.registration, "XYABC");
  assert.equal(result.cockpitCrew, 3);
  assert.equal(result.cabinCrewTotal, 5);
});

test("Y189 is never mined for a class layout", () => {
  const {d} = only(MSG);
  // The old defect surfaced as "PAX by class: Y 71" — a label taken from the class table
  // and a value taken from a single-valued .PAX/. Neither may happen.
  assert.equal(d.paxByClass, null, "single-valued .PAX/ must not become a class distribution");
  const json = JSON.stringify(parseLDM(MSG).result);
  assert.ok(!/"paxByClass":\[/.test(json), "no class array should appear in the result");
});

test("four-value passenger element splits M/F/C/I", () => {
  const {d} = only(MSG);
  assert.equal(d.male, 41);
  assert.equal(d.female, 28);
  assert.equal(d.adult, 69);
  assert.equal(d.child, 2);
  assert.equal(d.infant, 2);
});

test("infants are excluded from seated and included in the total", () => {
  const {d} = only(MSG);
  assert.equal(d.paxSeated, 71, "41 + 28 + 2");
  assert.equal(d.paxTotal, 73, "seated + 2 infants");
});

test(".PAX/ is kept as a reconciliation value, not a substitute", () => {
  const p = only(MSG);
  assert.equal(p.d.paxReportedTotal, 71);
  assert.equal(p.d.paxSeated, 71);
  assert.ok(checkFor(p, "pass", "reconciling with adults + children"),
    "a matching .PAX/ should produce a passing reconciliation check");
});

test("a disagreeing .PAX/ retains both values and fails the check", () => {
  // Same shape, but .PAX/ has the infants leaked in.
  const p = only(MSG.replace(".PAX/71", ".PAX/73"));
  assert.equal(p.d.paxSeated, 71, "derived count is untouched");
  assert.equal(p.d.paxReportedTotal, 73, "reported count is untouched");
  assert.ok(checkFor(p, "fail", "infants do not occupy a seat"));
});

test("souls on board counts infants and both crew groups", () => {
  const {result} = parseLDM(MSG);
  assert.equal(result.soulsOnBoard, 81, "73 passengers + 3 cockpit + 5 cabin");
});

test("main load data stays distinct from supplementary positions", () => {
  const {d} = only(MSG);
  assert.equal(d.totalDeadload, 1340);
  assert.deepEqual(d.compartments, {"4": 1340});
  assert.deepEqual(d.loadCategories, {B: 1340});
  // Compartment 4 must not be conflated with supplementary positions 41 / 42.
  assert.ok(!("41" in d.compartments), "41 is a supplementary position, not a compartment");
  assert.ok(!("42" in d.compartments), "42 is a supplementary position, not a compartment");
});

test("supplementary baggage correlates weights with piece counts", () => {
  const {result} = parseLDM(MSG);
  const si = result.supplementary;
  assert.deepEqual(si.holdPositions, [
    {position: "41", pieces: 80, weight: 1320},
    {position: "42", pieces: 2,  weight: 20},
  ]);
  assert.equal(si.bagPieces, 82);
  const pieces = si.holdPositions.reduce((a,p)=>a+p.pieces, 0);
  const weight = si.holdPositions.reduce((a,p)=>a+p.weight, 0);
  assert.equal(pieces, 82, "piece total");
  assert.equal(weight, 1340, "weight total");
});

test("operational remark is preserved verbatim", () => {
  const {result} = parseLDM(MSG);
  assert.deepEqual(result.supplementary.remarks, ["TRA BAGS LDD H41 DOORSIDE"]);
});

test("piece and weight totals both reconcile", () => {
  const p = parseLDM(MSG);
  assert.ok(checkFor(p, "pass", "matching <b>BPCS/</b>"));
  assert.ok(checkFor(p, "pass", "Supplementary hold weights sum to 1340"));
});

/* ---------------------------------------------------------------- generic behaviour */

test("a multi-valued .PAX/ is still an explicit class distribution", () => {
  const {d} = only(`LDM
XX0957/24.XYCDE.B772.3/9
-LHR.228/19/4/.T9974.AB/582/A2/532/A1/2915/F2/4202/F1/1743
.PAX/33/26/192`);
  assert.deepEqual(d.paxByClass, [33, 26, 192]);
  assert.equal(d.paxReportedTotal, null);
  assert.equal(d.paxSeated, 251);
});

test("an empty infant field leaves the total unknown rather than guessing zero", () => {
  const {d} = only(`LDM
XX0957/24.XYCDE.B772.3/9
-LHR.228/19/4/.T9974.AB/582`);
  assert.equal(d.infant, null);
  assert.equal(d.paxSeated, 251);
  assert.equal(d.paxTotal, null, "unknown infants means an unknown total, not 251");
});

test("three-value passenger elements keep the same infant rule", () => {
  const {d} = only(`LDM
YY847/24.XYDEF.50/24/202.3/10
-AMS.246/0/2.T9840
.PAX/48/24/174`);
  assert.equal(d.male, null);
  assert.equal(d.adult, 246);
  assert.equal(d.paxSeated, 246);
  assert.equal(d.paxTotal, 248);
});

test("more than two supplementary positions each keep their own row", () => {
  const si = parseLDM(`LDM
ZZ100/09.XYABC.Y150.2/4
-FRA.100/40/3/1.T2000.1/2000
SI
11/900.12/700.13/400
BPCS/60.11/25.12/20.13/15`).result.supplementary;
  assert.deepEqual(si.holdPositions, [
    {position: "11", pieces: 25, weight: 900},
    {position: "12", pieces: 20, weight: 700},
    {position: "13", pieces: 15, weight: 400},
  ]);
  assert.equal(si.holdPositions.reduce((a,p)=>a+p.weight,0), 2000);
});

test("a position present in only one line keeps a null for the missing side", () => {
  const si = parseLDM(`LDM
ZZ100/09.XYABC.Y150.2/4
-FRA.100/40/3/1.T1000.1/1000
SI
11/600.12/400
BPCS/30.11/30`).result.supplementary;
  assert.deepEqual(si.holdPositions, [
    {position: "11", pieces: 30, weight: 600},
    {position: "12", pieces: null, weight: 400},
  ]);
});

test("structured SI lines are not mistaken for free-text remarks", () => {
  const si = parseLDM(`LDM
XX0957/24.XYCDE.B772.3/9
-LHR.228/19/4/.T9974.AB/582
SI LHR B/4001.C/5731.M/242`).result.supplementary;
  assert.deepEqual(si.remarks, [], "a B/C/M breakdown is structured, not a remark");
  assert.equal(si.baggageWeight, 4001);
});

test("every bundled sample parses without throwing", () => {
  // Guards against a change that fixes one shape and breaks another.
  const samples = [MSG,
    `LDM
QQ8351/07.XYNKD.C16Y174.2/6
-VIE.77/108/4/4.0.T3973.F1/1112/FB/354/FA/419/FC/552/AB/1536.PAX
/108/39/42.PAD/5
SI VIE FRE 806 POS 0 BAG 3167 TRA 0`,
    `LDM
AB904/01.XYABC.1234.2/0
-BSL.A/65.C/920.D/1045.E/1121.K/65.TW3216
-GVA.B/740.F/2325.G/1874.H/1212.J/387.TW6538`];
  for(const s of samples){
    const p = parseLDM(s);
    assert.ok(p.result.destinations.length >= 1);
    assert.ok(!p.checks.some(([lvl,m]) => lvl==="fail" && /unrecognised/.test(m)));
  }
});
