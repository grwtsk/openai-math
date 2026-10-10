# Integrity and rigor evidence report

Frozen source: `openai/math@fd4aeeb2ee4fc729c18d98444fed42fd0529eeeb`

This report consolidates evidence that previously existed only in transient sandbox packages. It preserves distinctions between raw observations, derived interpretations, correction proposals, unreplayed Lean source, and accepted theorem evidence.

## Landau–Siegel audit wave

# Landau–Siegel audit wave

Frozen source: `fd4aeeb2ee4fc729c18d98444fed42fd0529eeeb`
Probe head: `288675c12d3f7dbde21c862894aa7c63446162cc`

## Geometric route

- Theorem: `OAI.SiegelZeros.WeightedTorusJets.exists_absolute_real_zero_gap`
- Module build: `0` in 478.442112 s
- Lean probe: `0` in 6.52107 s
- Raw axioms: `['Classical.choice.{u}', 'Quot.sound.{u}', 'propext']`
- Canonical axioms: `['Classical.choice', 'Quot.sound', 'propext']`
- Derived classification: `UNDERLYING_PRIMARY_LEAN_PROBE_SUCCEEDED__OFFICIAL_RECEIPT_REISSUE_REQUIRED`

## Analytic route

- Theorem: `OAI.SiegelZeros.WeightedTorusJets.dirichletRealZeroBound_proof`
- Module build: `0` in 589.21335 s
- Lean probe: `0` in 5.797698 s
- Raw axioms: `['Classical.choice.{u}', 'Quot.sound.{u}', 'propext']`
- Canonical axioms: `['Classical.choice', 'Quot.sound', 'propext']`
- Derived classification: `UNDERLYING_PRIMARY_LEAN_PROBE_SUCCEEDED__OFFICIAL_RECEIPT_REISSUE_REQUIRED`

## Route separation

- Shared local modules: **0**
- Shared source blobs: **0**
- Shared external imports: `['Mathlib']`
- Classification: `DISJOINT_LOCAL_DECLARATION_CLOSURES_WITH_SHARED_AGGREGATE_PENDING_CAUSAL_INDEPENDENCE_REVIEW`

## Boundary

The source receipts remain failed and are not rewritten. This report records why the failures are parser false negatives after successful builds and Lean probes. A corrected rerun is required before either target receives an official passing primary-kernel receipt.

## Landau–Siegel external-closure correction

# Landau–Siegel external-closure overlap correction

Frozen OpenAI source: `fd4aeeb2ee4fc729c18d98444fed42fd0529eeeb`  
Pinned Mathlib: `d13f23b723b8a846827a245b89c10fc7d3f11612`

## Retained positive result

The selected tracked OAI closures share **0 local modules** and **0 local source blobs**.

## Correction

The analytic route has 2 lexical external imports and the geometric route has 323. Their exact shared direct-import set is `['Mathlib']`.

That count is not an external dependency-closure overlap. `Mathlib` is a keep-all aggregate with public imports across the library surface. Both theorem environments therefore share a large external environment even though their tracked OAI source closures are disjoint.

Classification:

`LOCAL_SOURCE_SEPARATION_CONFIRMED__EXTERNAL_DECLARATION_OVERLAP_UNRESOLVED`

## Required next evidence

A route-independence receipt must expand external module closures and, more importantly, compare the elaborated constants referenced by the final theorem types and proof terms. Direct import strings are insufficient.

## Landau–Siegel statement bridge status

# Landau–Siegel statement bridge candidate

This package makes the precise statement-shape bridge explicit. The geometric route curries `0 < β`, `β < 1`, and the zero equation; the analytic route receives the same three propositions as a conjunction. The bridge transports the same existential witness `c` in both directions.

Status: **Lean source candidate, not yet replayed**. It must be compiled in the pinned theorem-probe environment before becoming an accepted formal receipt.

## Analytic Landau–Siegel contradiction review

# Analytic Landau–Siegel contradiction and subsingleton review

Frozen source: `openai/math@fd4aeeb2ee4fc729c18d98444fed42fd0529eeeb`

Target closure: `OAI.SiegelZeros.WeightedTorusJets.dirichletRealZeroBound_proof`

## Result

All **7** `False.elim` and **5** `Subsingleton.elim` occurrences reported by the static closure scanner were inspected in source context.

No sampled elimination derives the main result from an unintended globally empty or subsingleton mathematical model. The occurrences are:

- impossible branches in finite enumeration of units of `ZMod 8`;
- omitted-summand side conditions for finite sums;
- an explicitly empty-open branch;
- uniqueness of the point of `Spec` of a field;
- uniqueness of an index in `Fin 1`;
- a coefficient-ring branch explicitly guarded by `Subsingleton K`; and
- proof/typeclass witness reconciliation.

One restriction must remain prominent: `rectangularTaylorThree_one_first_order` assumes `hi : ∀ j, j = i`. Its `False.elim` is valid precisely because that theorem is restricted to a singleton index type. A downstream restatement must not erase this hypothesis.

Classification:

```text
BOUNDED_ELIMINATIONS_AND_EXPLICIT_EDGE_CASES
NO_UNINTENDED_GLOBAL_MODEL_COLLAPSE_FOUND_IN_THE_TWELVE_SAMPLED_SITES
```

## Boundary

This is source-context review, not a proof-term dependency audit or independent-kernel receipt. The JSON record gives the per-site classification and retained caveats.

## Quasi-Riemann patched-dependency issue draft

# Audit the quasi-Riemann theorem’s directly patched external modules

Umbrella: #2

Related theorem audit: #14  
Related effective-dependency owner: #22  
Related adapted PNT+ source owner: #43  
Related theorem receipts: #13  
Related import and elaboration receipts: #39

## Finding

The selected theorem

```text
OAI.riemannZeta_ne_zero_of_seven_eighths_lt_re
```

has a static local OAI import closure of 2,924 modules. Its external package
roots include:

```text
Lean
Mathlib
PrimeNumberTheoremAnd
RellichKondrachov
```

Two imported external modules intersect compatibility-patched files exactly.

### PrimeNumberTheoremAnd

The closure imports:

```lean
import PrimeNumberTheoremAnd.Wiener
```

through both:

```text
OAI.NumberTheory.DirichletL.IdealMangoldt
OAI.NumberTheory.DirichletL.PrimeCounting.Progressions
```

The shortest recorded local paths include:

```text
Nonvanishing
→ Detector.FinalAssemblyUnconditional
→ Detector.FinalAssemblyCertifiedBands
→ Detector.DetectorInverseFields
→ Detector.DetectorInverseRawField
→ Detector.DetectorMomentData
→ PrimeRows.CanonicalRayCube
→ Detector.RayCharacterFamily
→ Detector.RayPhaseAmplitude
→ Detector.RaySlots
→ RayPrimeNormalizer
→ Hecke.RayPrimes
→ PrimeCounting.IdealPrimeMass
→ IdealMangoldt
→ PrimeNumberTheoremAnd.Wiener
```

and the analogous route through `PrimeCounting.PrimeMass` and
`PrimeCounting.Progressions`.

This is not merely an ambient import. `Progressions.lean` directly invokes
`WienerIkeharaTheorem'`; `IdealMangoldt.lean` invokes
`vonMangoldt_cheby` and the von-Mangoldt L-series summability interface.

The effective PNT+ checkout is:

```text
nominal commit:
  c39a751132c88b6e8080b74c74023fd95b3d8be0

post-patch tree:
  b7d455a31f9799c7b2b3485f3627f394db356064

package binary-diff SHA-256:
  45c98ef9fb852ee0201e3922c27216e47b5484fef7277300754db63e909c6bda
```

The 1,993,197-byte patch
`PrimeNumberTheoremAnd-lean4341.patch` has SHA-256:

```text
0890432340c0025973bcfe070b634355fa366cc831595f68526e4c73c8903d82
```

and modifies the exact imported file:

```text
PrimeNumberTheoremAnd/Wiener.lean
```

### RellichKondrachov

The closure reaches the external package after only two local edges:

```text
OAI.NumberTheory.DirichletL.Nonvanishing
→ OAI.NumberTheory.DirichletL.Foundation
→ OAI.NumberTheory.DirichletL.CubicSieve.RadialWindows
→ RellichKondrachov.Analysis.FunctionalSpaces.Sobolev.Euclidean.Rellich
```

The effective Rellich–Kondrachov checkout is:

```text
nominal commit:
  70f85d4c1bf99c6e7d61e8be4daa6f3664d08d23

post-patch tree:
  bfcc493ea4ec5071682badfba06ea30c0f40c2eb

package binary-diff SHA-256:
  0c121d8517dfeadc93ef24fe2deb56beec7cb3998e2552dee8f61c780b1408c8
```

The compatibility patch modifies the exact imported file:

```text
RellichKondrachov/Analysis/FunctionalSpaces/Sobolev/Euclidean/Rellich.lean
```

Source-level import reachability does not yet establish which Rellich
declarations occur in the elaborated proof term. That question remains open
and must not be resolved by visual inspection of one large importing file.

## Integrity consequence

The theorem cannot be identified completely by:

```text
OpenAI source commit
+ nominal dependency commits
```

Its current formal-source identity includes the post-patch PNT+ and
Rellich–Kondrachov trees.

The evidence must distinguish:

1. package processed by Lake;
2. module imported in the theorem’s source closure;
3. declaration referenced by the elaborated theorem or proof;
4. patch hunk affecting that declaration;
5. statement, proof, definition, reducibility, instance, or build-only change.

The PNT+ Wiener relation has direct source-level declaration use. The
Rellich relation currently has exact module-path intersection but unresolved
declaration use.

## Required work

1. Extract the elaborated constant dependency graph for the selected theorem.
2. Identify every referenced declaration supplied by
   `PrimeNumberTheoremAnd.Wiener`.
3. Identify every referenced declaration supplied by the Rellich import, or
   prove the import is eliminable without changing the theorem and proof.
4. Compute pre-patch and post-patch fingerprints for those declarations:
   elaborated type, value/body digest, reducibility, attributes, transitive
   axioms, imported instances, and namespace identity.
5. Classify each relevant patch hunk as syntax/toolchain port, API adaptation,
   statement change, proof change, definition change, instance change,
   reorganization, or mixed.
6. Build nominal and patched dependency modules separately under named
   toolchains and retain both logs.
7. Minimize the theorem shard’s imports and rerun the theorem probe.
8. Bind the primary-kernel, Comparator, and independent-kernel receipts to
   the same effective post-patch dependency trees.
9. Retain upstream source authorship, patch authorship, reviewers, licensing,
   and institutional packaging as separate relations.
10. Add hostile controls where a relevant dependency statement or instance is
    modified while the nominal upstream commit remains fixed; the theorem
    receipt must become stale.
11. Do not grant `COMPATIBILITY_PATCH_ONLY` until every relevant declaration
    has received semantic review.
12. Keep the totalized Lean value at `s = 1` separate from the paper’s
    meromorphic zero-free claim, as required by #14.

## Acceptance

- Every external declaration used by the theorem is mapped to an exact
  nominal and effective source identity.
- An unused import is distinguished from a proof-term dependency.
- Every patch hunk affecting a used declaration has a semantic-change class.
- The theorem replays from a bounded import closure.
- The receipt names the effective PNT+ and Rellich trees, not only their
  nominal commits.
- Public language remains limited to the formalized `Re(s) > 7/8` result and
  its explicit totalization convention.

## Non-claims

This finding does not allege that either compatibility patch is incorrect,
that Rellich compactness is necessarily essential to the final theorem, or
that the quasi-Riemann theorem fails. It identifies formal-source and
dependency-provenance obligations that remain unresolved.

## Quasi-Riemann import minimization

# Quasi-Riemann import-minimization addendum

## PNT+ Wiener

Classification: `EXPLICIT_SYMBOL_DEPENDENCY`.

The local prime-counting bridge calls Wiener/PNT+ declarations explicitly. Because the exact upstream file is patched, declaration-level pre/post fingerprints and semantic patch review are required.

## Rellich–Kondrachov

Classification: `AMBIENT_IMPORT_DEPENDENCY_UNRESOLVED`.

`OAI.NumberTheory.DirichletL.CubicSieve.RadialWindows` directly imports the patched Rellich module, but the fetched source contains no other `Rellich` occurrence and no `isCompactOperator` occurrence. That is strong evidence for an import-minimization experiment, not proof that the import is irrelevant.

The accepted test is a clean, cache-free rebuild after removing only that import, followed by theorem-type, axiom, proof/export, and dependency-fingerprint comparison.

## Theorem dependency projection

# Theorem dependency projection

Frozen upstream: `fd4aeeb2ee4fc729c18d98444fed42fd0529eeeb`

## Result

The global Lake environment contains **42**
Git packages and applies **23**
compatibility patches totaling **7,619,294 bytes**.
That is an operational environment receipt, not a minimal theorem dependency receipt.

### Landau–Siegel analytic route

- Local OAI closure: **67 modules**
- External package roots: `['Mathlib', 'PrimeNumberTheoremAnd']`
- Direct external import: `PrimeNumberTheoremAnd.SiegelZeros.HadamardSupport`
- PNT+ modules built in the observed run: **12**
- Relevant compatibility patch: `PrimeNumberTheoremAnd-lean4341.patch`
- Module build exit: **0**
- Lean probe exit: **0**

### Landau–Siegel geometric route

- Local OAI closure: **201 modules**
- External package roots: `['Lean', 'Mathlib']`
- PNT+ modules built in the observed run: **0**
- `PrimeNumberTheoremAnd` is absent from the static logical import roots.
- Module build exit: **0**
- Lean probe exit: **0**

Thus the PNT+ compatibility patch belongs to the analytic route's current logical
source boundary, but not to the geometric route's current source import closure.
Both runs still processed the same global Lake package graph.

### Quasi-Riemann static projection

- Local OAI closure: **2924 modules**
- External package roots: `['Lean', 'Mathlib', 'PrimeNumberTheoremAnd', 'RellichKondrachov']`
- PNT+ import: `['PrimeNumberTheoremAnd.Wiener']`
- Rellich–Kondrachov import: `['RellichKondrachov.Analysis.FunctionalSpaces.Sobolev.Euclidean.Rellich']`
- Relevant patches at package-root granularity:
  `['PrimeNumberTheoremAnd-lean4341.patch', 'rellich-kondrachov-lean4341.patch']`

## Required standard

Every theorem receipt should distinguish:

1. the logical imported module and package closure;
2. patched trees that actually supply declarations to that closure;
3. packages processed only because of the global Lake configuration;
4. modules compiled fresh versus restored from a named cache;
5. declaration-level fingerprints before and after each relevant patch.

A global package manifest remains valuable, but it must not be described as the
theorem's minimal logical dependency closure.

## Limits

This is a cross-artifact interpretation of static closure receipts and primary
build logs. It does not replace Lean environment dependency extraction,
Comparator, independent-kernel replay, or declaration-level semantic patch
review.

## Theorem-closure interpretation

# Theorem-closure interpretation review

- Frozen upstream base: `fd4aeeb2ee4fc729c18d98444fed42fd0529eeeb`
- Inventory SHA-256: `b5dd7ac7b7bc059959417e53ea9525fb3ba0dcee794424882eb6364b80864be9`
- Base scanner SHA-256: `83107350c8af3f2b43ca642a4d984949337f4f9f05304bc772eb791795a35489`
- Review scanner SHA-256: `bbc086208a6e71c69df09740b7b2977176af04607cf5e17b9b34ef9b70684b46`

## Statement and Comparator binding

### `quasi_riemann_zeta`

- Configured solution module: `OAI.NumberTheory.DirichletL.Nonvanishing`
- Declaration root: `OAI.NumberTheory.DirichletL.Nonvanishing`
- Relation: `CONFIGURED_SOLUTION_ROOT`
- Reachable from configured solution: **True**
- Critical static policy findings: **0**
- Independent-kernel flag: `False`
- Exact normalized challenge/solution statement hash for `OAI.riemannZeta_ne_zero_of_seven_eighths_lt_re`: **True**

### `landau_siegel_geometric`

- Configured solution module: `OAI.NumberTheory.SiegelZeros.Main`
- Declaration root: `OAI.NumberTheory.SiegelZeros.Conclusions.Theorem`
- Relation: `TRANSITIVE_DECLARATION_ROOT`
- Reachable from configured solution: **True**
- Critical static policy findings: **0**
- Independent-kernel flag: `False`
- Exact normalized challenge/solution statement hash for `OAI.SiegelZeros.WeightedTorusJets.exists_absolute_real_zero_gap`: **True**
- The first-pass `solution_module_mismatch` is reclassified as an expected declaration root beneath the configured aggregate, not as a Comparator defect.

### `landau_siegel_analytic`

- Configured solution module: `OAI.NumberTheory.SiegelZeros.Main`
- Declaration root: `OAI.NumberTheory.SiegelZeros.Characters.DirichletRealZeroBoundProof`
- Relation: `TRANSITIVE_DECLARATION_ROOT`
- Reachable from configured solution: **True**
- Critical static policy findings: **0**
- Independent-kernel flag: `False`
- Exact normalized challenge/solution statement hash for `OAI.SiegelZeros.WeightedTorusJets.dirichletRealZeroBound_proof`: **True**
- The first-pass `solution_module_mismatch` is reclassified as an expected declaration root beneath the configured aggregate, not as a Comparator defect.

## Landau–Siegel route relation

- Geometric local modules: **201**
- Analytic local modules: **67**
- Shared local modules: **0**
- Shared source blobs: **0**
- Shared external import roots: **1**
- Shared external imports: `Mathlib`
- Shared configured solution aggregate: **True** — `OAI.NumberTheory.SiegelZeros.Main`
- Classification: `DISJOINT_LOCAL_DECLARATION_CLOSURES_WITH_SHARED_AGGREGATE_PENDING_CAUSAL_INDEPENDENCE_REVIEW`

The selected local source closures share no tracked module or source blob, but both are exported through one Comparator solution aggregate and both depend on external libraries. This supports formal route separation; it does not establish causal, conceptual, or mathematical independence.

## Boundary

Exact source-region hash equality proves textual statement identity after whitespace normalization. It does not replace Lean elaboration, definitional-dependency comparison, Comparator replay, `#print axioms`, independent-kernel replay, or mathematical review.

## Validation

- All interpretation checks passed.
