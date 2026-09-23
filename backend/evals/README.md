# Evals: cheap mode and gate mode

Every runner here calls the real pipeline against the real corpus with the
flags as set in the environment. Nothing persists (commit is flush, the
session is rolled back). Two ways to run them:

| | Cheap mode (iterate) | Gate mode (decide) |
|---|---|---|
| Purpose | see which way a change points, in minutes | pass or fail a flag, per CLAUDE.md invariant 3 |
| Items | `--subset smoke`: 8 agentic + 5 risk-tier items, one or two per bucket (`smoke_subset.json`) | the full set (48 agentic, 14 risk-tier, 14 clarify, 30 guard, 46 verifier probes) |
| Draws | 1 | 3 where the runner has `--repeats` (clarify, risk-tier, guard, verifier probes); value gates by majority, absolute gates summed over draws |
| Judge | `--judge-model gpt-4o-mini` | the model the saved baseline was judged with (recorded in the run file as `judge_model`) |
| Verifier | `VERIFY_MODEL=openai:gpt-4o-mini` (set by `--cheap` unless you set it) | `openai:gpt-4o`, the production default since ADR-25 |
| Baseline | `--baseline evals/runs/<saved>.json` | the same saved run file, never a fresh flag-off run |
| Numbers | directional only, never quoted as a gate result | the numbers that go in the ADR |

`--cheap` is the preset for the left column on the agentic and risk-tier
runners: smoke subset, mini judge, mini verifier unless `VERIFY_MODEL` is
already set. With `--only <ids>` the named items are the subset (the smoke
subset is not applied on top; before 23 Sep 2026 the two intersected and a
`--cheap --only` run silently ran nothing). A cheap or non-default run prints
a NOTE line saying so.

```
# cheap: which way is the change pointing?
APP_ENV=test AGENTIC_RAG=1 python evals/run_agentic_eval.py --cheap --baseline evals/runs/adr30_guard_on_agentic_j2.json --json /tmp/smoke.json
APP_ENV=test AGENTIC_RAG=1 CLARIFY_FOLLOWUP=0 RISK_TIER_FRAMING=1 python evals/run_risk_tier_eval.py --cheap

# gate: the run that decides
APP_ENV=test AGENTIC_RAG=1 python evals/run_agentic_eval.py --baseline evals/runs/adr30_guard_on_agentic_j2.json --json evals/runs/<name>_j2.json
APP_ENV=test AGENTIC_RAG=1 CLARIFY_FOLLOWUP=0 RISK_TIER_FRAMING=1 python evals/run_risk_tier_eval.py --repeats 3 --json evals/runs/<name>.json
APP_ENV=test AGENTIC_RAG=1 python evals/run_intent_eval.py --clarify --json evals/runs/<name>.json   # three times for the split gate
APP_ENV=test python evals/run_guard_eval.py --repeats 3
APP_ENV=test python evals/run_verify_probes.py --model openai:gpt-4o --repeats 3 --headings
```

## Comparing against a saved baseline

`--baseline` compares item by item with a saved run file: the deterministic
fields (context recall, predicted abstention, citation accuracy) must match
on every shared item, the judged metrics are printed side by side, and items
missing from the baseline are listed rather than compared. Do not regenerate
the flag-off run to compare; the saved file is the baseline. Current
baselines: `adr32_recitals_on_agentic_j2.json` (on-topic, 52 items with the why
bucket; `adr30_guard_on_agentic_j2.json` is the 48-item run before the recitals),
`risk_tier_off_j2.json` (risk-tier, flag off), `clarify_adr26_draw3_j2.json`
(clarify), `verify_probes_adr26_gpt-4o.json` (verifier), `guard_probes_adr30.json`
(guard).

## The judge model, stated plainly

The faithfulness and relevance judge has been `gpt-4o-mini` since ADR-20; every
saved baseline was scored with it, and run files from ADR-31 on record
`judge_model`. `--judge-model gpt-4o` is available, but a gate run judged by a
different model than its baseline compares nothing on the judged metrics: a
switch of the gate judge means re-baselining the on-topic set first. The
deterministic metrics, the verdict-leak count and the per-item outcomes do
not depend on the judge and stay comparable across judges.

## Run discipline

One eval at a time (parallel runs have exhausted the database pooler), run
detached with `nohup` and a log, `python -u`, no dev server alongside. Runs
longer than ten minutes do not survive the shell's background timeout, and a
sleeping laptop drops the pooler connection; the risk-tier runner writes its
JSON per item and loses nothing, the others lose the run.
