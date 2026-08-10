# LDM Parsing Benchmark

Measures whether the `ldm-message-parsing` skill improves structured extraction from raw
IATA Type B LDM messages, compared to the same model with no domain knowledge injected.

## Running it

```bash
pip install anthropic
export ANTHROPIC_API_KEY=sk-ant-...

python generate_testset.py -n 40 --seed 20260801
python run_benchmark.py --repeats 5 --model claude-sonnet-4-6
python report.py results.json
```

Cost is roughly `2 arms x n_cases x repeats` requests. At n=40, repeats=5 that is 400 calls;
the skill arm carries a ~25k character system prompt, the baseline arm does not.

## Methodology

**Test set is generated from ground truth, not annotated.** `generate_testset.py` samples a
point in the variant space, constructs the underlying load figures, then *renders* the message
from them. The gold answer is therefore correct by construction — there is no annotator error
floor. Arithmetic is internally consistent: compartment weights sum to total deadload, and the
`.PAX/` class array sums to seated passengers.

Variant axes sampled:

| Axis | Values |
|------|--------|
| `version_style` | seat map single / seat map multi / aircraft type / slash counts / carrier code |
| `crew_shape` | two-part / three-part with gender split |
| `pax_form` | A/C/I / M/F/C/I / M/F/C/I with empty infant field |
| `comp_join` | full-stop joined / slash joined |
| `si_pattern` | none / B-C-M-E / hold-level + BPCS / labelled free text |
| `wrap` | clean lines / hard-wrapped at 64 chars mid-element |
| `n_dest` | 1 / 2 / 3 destinations |

**Both arms receive the identical output schema and the identical task instruction.** The only
difference is the presence of the skill markdown in the system prompt. Withholding the schema
from the baseline would measure schema-guessing rather than domain knowledge and would produce
a headline number that does not survive scrutiny.

**Repeats and variance.** Every case is run `--repeats` times per arm. `report.py` computes the
standard deviation across repeats, so a difference smaller than the run-to-run noise is visible
as such rather than being reported as a result.

## Scoring

Field-level exact match, grouped into six categories, so the report shows *where* knowledge
helps rather than a single opaque percentage:

- **Flight record** — airline, flight number, day, registration, version, crew
- **Passenger counts** — male, female, adult, child, infant, seated total
- **Deadload / weights** — total deadload, cabin baggage
- **Compartment map** — designator-to-weight mapping, exact
- **PAX class array** — per-cabin passenger distribution
- **SI breakdown** — baggage / cargo / mail weights

Two **critical error** classes are tracked separately, because they are silent — the output is
well-formed and plausible, and wrong:

- `infant_in_pax` — infants counted as seated passengers, inflating load factor and any
  per-passenger billing derived from it
- `compartment_ids_wrong_sum_right` — weights correct, designators wrong; totals reconcile, so
  no downstream validation catches it

`unparseable_output` covers responses that were not valid JSON.

## Interpreting the result

The expected story is **not** "the model could not do this and now it can". A capable model
produces reasonable output on a clean single-destination LDM without any help. The differences
should concentrate in:

- messages hard-wrapped mid-element
- compartment lists using slash-joined or alpha designators
- the empty-infant-field variant
- distinguishing unlabelled cabin baggage weight from the passenger array
- deciding whether an absent gender split means zero or unknown

Report what the numbers actually show, including the axes where the gap is small. A benchmark
that claims uniform improvement everywhere invites the reader to doubt all of it.
