# Selection-boundary experiment (fork-side audit only)

Scope: issues #44, #45, #46, #47, #48, #50, #51, #52, #53 in `grwtsk/openai-math`.

**NOT FOR MERGE TO MIRROR `main`.** This tooling is an audit fixture, not part of the `openai/math` mathematical release. Source identity is frozen to `openai/math@fd4aeeb2ee4fc729c18d98444fed42fd0529eeeb`. It does not call an OpenAI internal model, read unpublished prompts, or infer actual model hand tuning.

## Reproduce

```sh
python3 audit/selection_integrity/experiment.py --mode all --out /tmp/selection-results.json
python3 -m unittest discover -s audit/selection_integrity -p 'test_*.py' -v
```

Python stdlib only. The script verifies exact Git blob hashes for `CONTENTS.md` and `README.md` before extracting 372 family records, manuscript counts and ten reasoning-summary indices. Fails closed if the release changes; never silently runs against a different corpus. Use `--mode synthetic` to run the controlled factorial without a checkout.

## Experiments and interpretation

**Public-data layer:** Test the pre-existing exploratory `digit 7` observation as an exact finite-population hypergeometric overlap. Correct *within the family of ten single-digit hypotheses only* via 5,000 random subsets, and report selection into reasoning summaries versus manuscript count and maximum CUSUM of manuscript counts along catalogue order. These are **descriptive catalogue effects**, not model-choice, mathematical-content, attack, or process-time measurements. Catalogue order is not attempt chronology; exchangeability and a uniformly sampled set of ten are generally implausible. Digit selection was post hoc, and testing more OEIS families increases the multiplicity burden further. Do not treat nominal or ten-digit FWER p-values as confirmatory.

**Controlled factorial layer:** For each synthetic task, draw a common latent quality and *freeze two numerical generator outputs* across filter arms. Test a no-injected-effect baseline, an explicitly shifted presentation-conditioned filter threshold, a shifted generator score, and their combination, with identical underlying task quality and paired budgets. Exact two-sided McNemar tests provide a paired asymmetry check. Calibrate the synthetic negative/positive controls across repeated seeds, alpha 0.01. The assignments are randomized but baseline mathematical equivalence is **stipulated** by the synthetic construction, not proved for any real natural-language problem. This layer validates a detection mechanism only. A significant injected effect must **never** be reported as evidence that OpenAI applied such a filter.

## Next steps toward actual model-quality improvement

1. Integrate this fixture into a dedicated audit/testing location, never the upstream mirror. When a callable model is available, freeze checkpoint + decoding + tools + compute and record candidate outputs **before** a frozen filter; then replay identical candidates through comparator filters. Preregister equivalent formulations and confirm mathematical equivalence independently.
2. Give generator and filter different, immutable version IDs. For each stage log consented task and attempt hashes, outcomes, retries, interventions, and missingness. Separate private raw data from minimal public counts and attestations.
3. Compare paired acceptance differences against a randomized same-prompt baseline. Require replication on held-out families, controls for reviewer/topic/time, and an evidence grade before describing a live failure.
4. Route discovered model-quality regressions into a reversible evaluation suite, not an automatic or unreviewed change to model weights. Explicitly preserve human review and provenance.

**Strongest permissible conclusion without original logs:** `INTERNAL_GATE_UNTESTED`; `SELECTION_IDENTIFIABILITY_BLOCKED`. Any systematic signal measured in release-order data is `PUBLIC_RELEASE_ORDER_ASSOCIATION`, not evidence of a security event.
