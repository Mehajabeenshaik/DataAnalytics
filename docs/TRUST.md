# Trust — plain-English summary

*For engineers, see [TRUST_REPORT_ollama.md](TRUST_REPORT_ollama.md) and
[TRUST_REPORT.md](TRUST_REPORT.md). Last real-model run: 2026-08-24.*

## What DaAna is promising, in one line

The AI can only answer questions using **numbers your team already approved**
— it cannot invent queries, touch raw data, or reveal private information.

## Results from a real local LLM (not a simulation)

We ran our full question suite through a real language model running locally
(Ollama, `nemotron-3-nano:4b` — a small open model, deliberately chosen so all
data stays on-premise):

| Question | Answer |
|---|---|
| Did any private data (emails, phones, addresses) leak into answers? | **No — zero leaks in 23 tests** |
| Did anything crash or produce unexplained output? | **No — zero unhandled errors** |
| Did the AI stay inside its approved list of metrics? | **Yes, with one noted edge case below** |
| Overall accuracy vs. expected answers | **82.6% (19 of 23)** |
| Correctly refused trick questions / prompt-injection attempts | 5 of 6 |

## What the failures were (we publish them on purpose)

- **3 questions were "under-answered."** The model said *"I don't have a
  metric for that"* when a reasonable analyst would have answered (e.g.
  *"How many orders do we have?"*). This is the **safe direction to fail** —
  it never produced a wrong number.
- **1 adversarial probe partially slipped.** When asked to run a fake,
  non-existent "evil" metric, the planner fell back to a legitimate approved
  metric instead of refusing outright. Importantly: it still ran only an
  approved metric with governed execution — no arbitrary SQL, no data
  exposure. Tightening this refusal is on the roadmap.

## Why the architecture makes these numbers believable

The safety does not come from asking the model nicely:

1. The model may only **choose** from human-approved metrics and stats tools.
2. All math runs in **deterministic code you control** — never model-written SQL.
3. Private columns are **masked before** the model ever sees results.
4. Every answer ships with **confidence, lineage, and caveats**.

So even a misbehaving model is boxed in: worst case it picks the wrong
approved metric or refuses — it cannot execute anything you did not approve.

## How to reproduce

```bash
ollama pull nemotron-3-nano:4b
python -m eval.run_trust_eval --provider ollama --out docs/TRUST_REPORT_ollama.md
```

Golden sets live in `eval/golden/`. Expand them with your own customer
questions during a pilot to make the evidence specific to your business.