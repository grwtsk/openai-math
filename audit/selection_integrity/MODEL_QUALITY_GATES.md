# Model-quality regression gates from selection-integrity audits

Audit-side proposal only. No model weights, serving filters, or production policy are changed by this PR. Applicable to a model or research kernel only when an authorized owner supplies an evaluation adapter and approves the protected data boundary.

## Measurement contract

Every evaluable case must retain independently versioned records for:

- **Human problem intent and source provenance:** target statement, equivalence declaration, correction attribution, consented source links, and mathematical verification status;
- **Generator:** fixed model/checkpoint identity, decoding configuration, seed(s), tool/retrieval snapshot, raw candidate identity, budget, timestamps or causal sequence, and rejected candidates where permitted;
- **Filter:** distinct versioned policy and threshold, input candidate digest, feature extract, decision, score, reason, intervention/override, and evaluation authority;
- **Selection outcome:** attempted, generated, solved, verified, reviewed, published, corrected, withdrawn, credited; no conflation of stages.

Keep access-restricted raw logs private. Public receipts should contain only safe content hashes, counts, protocols, aggregate effect estimates and independent attestation grades. Absence of private logs is *unknown*, not proof of failure or absence of human participation.

## Gates before making model-improvement claims

**MG-0: Source and authority.** Pin generator/filter/environment revisions and evaluation inputs; mark synthetic fixtures, live adapter observations, and upstream-public observations separately. Refuse automatic promotion when sources or human permissions are unresolved.

**MG-1: Equivalence integrity.** Preregister tasks with independently verified mathematical equivalence of notation, alpha-renaming, permutations, and logically identical goal statements. Separate genuinely harder tasks and changed retrieval overlap. Do not infer semantic equivalence from lexical similarity.

**MG-2: Paired and factorial discrimination.** Freeze generator candidates, compare F0 vs F1 filters on identical candidate hashes. Freeze F0, compare G0 vs G1 raw generator outputs. Use a 2×2 randomized crossover, preserve intervention provenance, and analyze paired effects using exact McNemar or a preregistered hierarchical model with appropriate clusters. Test equal-prompt repeat noise before alleging presentation sensitivity.

**MG-3: Controls and statistical validity.** Include negative controls, an injected positive control, preregistered alpha/effect size/number of looks, multiplicity correction, sample-size/power analysis, and a held-out confirmation set. Do not use catalogue order as internal event time, or assume that post-publication survivors represent all attempts.

**MG-4: User and human contribution reciprocity.** Make correction and attribution review written-first and accessible. Distinguish theorem origin, strategy, coding, verification, editorial feedback, and release approval. Human acceptance/overrides require declared authority; no silent alteration of human intent through optimization of a proxy metric.

**MG-5: Decision and action.** 
- `PASS`: a preregistered, adequately powered holdout shows no material degradation beyond a declared bound and no source/authority violations.
- `FAIL`: replicated, causally localized regression with evidence grade and minimized reproduction; issue a human-review checkpoint and propose a reversible correction.
- `INDETERMINATE`: missing denominator, uncertain equivalence, underpowered test, unavailable logs, conflicting scope, or nonreproducible result. Do not silently classify as pass or fail.

For any candidate improvement, report task quality, verification integrity, candidate coverage, human corrections preserved, false acceptance, false rejection, performance across challenge strata, resources consumed, and whether the gain comes from G or F. An increase in publication acceptance alone is not evidence that the underlying model improved.

## Initial baseline from the executed synthetic fixture

- 1,200 paired tasks; injected 0.08 filter threshold shift shows -6.83 percentage-point variant acceptance difference while generator outputs remain frozen.
- Injecting a generator score shift of 0.08 under the unchanged filter produces the same binary acceptance results. Decision logs alone cannot identify the locus of the change.
- Thirty-six simulated calibration seeds detect the inserted filter change 36/36 times at alpha=0.01; the negative control raised one false alert. This is a fixture test, not a model reliability claim.

## Required next adapter, not included in this PR

A consented local/hosted callable model with explicit generator output export, a deterministic filter replay interface, truly equivalent mathematical problem variants, and authorized compute. Without this adapter the only honest live status is `INTERNAL_GATE_UNTESTED` and `SELECTION_IDENTIFIABILITY_BLOCKED`.

Related: #44, #45, #46, #47, #48, #51, #52, #35. The fork's upstream-mirror `main` remains unchanged.
