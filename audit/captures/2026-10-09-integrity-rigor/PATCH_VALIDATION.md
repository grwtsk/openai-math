# Audit-tool correction validation

## Selected theorem kernel-probe correction

# Selected theorem kernel-probe correction

This patch repairs the false-negative classification observed in workflow run
`37918800748`. Both Landau–Siegel module builds and Lean probes exited zero.
The previous receipt parser compared Lean's raw universe-polymorphic names
`Classical.choice.{u}` and `Quot.sound.{u}` directly with the canonical
allowlist names.

The correction preserves raw evidence, canonicalizes only terminal Lean
universe instantiations for policy comparison, hardens comma parsing inside
`.{u, v}`, bumps the receipt schema to `SelectedTheoremKernelProbe/2`, and
blocks unexpected source-tree mutation. The workflow also disables Python
bytecode emission so `__pycache__` does not contaminate repository-status
evidence.

Patch SHA-256: `85d6d2c465faa4b6c985daacb2bc20c71692acebcef401d4d54732f8b0d6fd6a`

Validation details are in `validation.txt`.

### Validation output

```text
Validated normalization core
============================

Base branch: audit/theorem-kernel-probes-20261009
Base head: 288675c12d3f7dbde21c862894aa7c63446162cc

Observed Lean output:
  [propext, Classical.choice.{u}, Quot.sound.{u}]

Policy result after canonicalization:
  raw:       [Classical.choice.{u}, Quot.sound.{u}, propext]
  canonical: [Classical.choice, Quot.sound, propext]
  unexpected: []

Safety controls exercised:
- preserves raw names;
- strips only a terminal `.{...}` universe instantiation;
- parses commas inside multi-universe instantiations;
- rejects malformed brace structure;
- rejects empty list tokens;
- keeps an unknown universe-polymorphic axiom unknown;
- does not strip nonterminal braced text;
- separates expected receipt output from source-tree mutation.

Local dependency-free validation: 11 tests passed.
Authoritative theorem receipts still require a new GitHub Actions run after the patch is applied.
```

## Comparator-closure parser hardening

# Comparator-closure parser hardening

This package is an audit-side correction proposal for draft PR #49. It does not modify the frozen mirror.

## Defects addressed

1. `public theorem` and `public def` were invisible to the declaration regex.
2. A `private theorem` could be reconstructed as an exported full name and falsely pass `EXACT_IN_SOLUTION_CLOSURE`.
3. `mutual ... end` was not represented as a lexical block, so its `end` could pop an enclosing namespace.
4. `public section ... end` and `private section ... end` were not represented, with the same namespace-corruption risk.
5. `namespace _root_` did not reset the accumulated namespace.
6. Dots inside `«guillemet identifiers»` were split as namespace separators.
7. A labelled `end` searched backward and deleted multiple frames; Lean closes one lexical block.

The patch bumps the report and receipt schemas to version 2. It remains a static scanner, not a Lean parser. Exact target acceptance should still be followed by Lean environment resolution.

## Validation

The included dependency-free reference implementation passed seven hostile tests covering each corrected boundary. The repository scanner should rerun after applying the patch, and the pre-hardening result should not be accepted as final evidence.

### Validation output

```text
test_end_closes_only_one_scope (test_parser_hardening_reference.Tests.test_end_closes_only_one_scope) ... ok
test_guillemet_dot (test_parser_hardening_reference.Tests.test_guillemet_dot) ... ok
test_mutual_scope (test_parser_hardening_reference.Tests.test_mutual_scope) ... ok
test_private (test_parser_hardening_reference.Tests.test_private) ... ok
test_public (test_parser_hardening_reference.Tests.test_public) ... ok
test_public_section_scope (test_parser_hardening_reference.Tests.test_public_section_scope) ... ok
test_root_namespace (test_parser_hardening_reference.Tests.test_root_namespace) ... ok

----------------------------------------------------------------------
Ran 7 tests in 0.001s

OK
```

## Metaprogramming-surface calibration

# Metaprogramming-surface calibration

The theorem-closure scanner currently labels an import such as `import Lean.Elab.Tactic.Omega` as “Direct elaborator/metaprogramming API use.” That is too strong. An import is an elaboration-tool dependency; a source-level reference such as `Lean.Meta.mkAppM` is direct API use; `run_tac` is executed metaprogrammed proof generation. These are distinct trust surfaces.

The patch splits them into:

- `elaboration_tool_import` — review severity;
- `lean_elab_api` — medium severity, only outside import commands;
- `run_tac` — medium severity and independently retained.

This calibration preserves every signal while preventing an import-only dependency from being reported as direct API programming.

### Validation output

```text
test_api (test_reference.T.test_api) ... ok
test_import (test_reference.T.test_import) ... ok
test_public_import (test_reference.T.test_public_import) ... ok
test_run_tac (test_reference.T.test_run_tac) ... ok

----------------------------------------------------------------------
Ran 4 tests in 0.000s

OK
```

