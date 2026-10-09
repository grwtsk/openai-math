# Captured Genesis integrity evidence

Frozen source: [`openai/math@fd4aeeb2ee4fc729c18d98444fed42fd0529eeeb`](https://github.com/openai/math/commit/fd4aeeb2ee4fc729c18d98444fed42fd0529eeeb)

Capture branch: `audit/genesis-integrity-capture-20261009`

Effect class: **AUDIT ONLY — DO NOT MERGE INTO THE UPSTREAM-MIRROR `main` BRANCH**

The content-addressed archive preserves the correction packages and review records that previously existed only in transient sandbox files. Its reconstructed identity is:

```text
filename: genesis-integrity-capture.tar.gz
bytes:    69,953
sha256:   5664663da5c4ca437602c9d5e972f06c9cffac7aae7fda775ea05ba81b83a963
```

The archive is reconstructed and verified with `reconstruct_archive.py`; its internal `reconstruct.py` restores every embedded artifact and checks its individual SHA-256.

## Package register

| Package | Files | Envelope SHA-256 | Original ZIP SHA-256 | Primary owner |
|---|---:|---|---|---|
| `kernel-probe-correction` | 5 | `b2c1c95c6a5f5901e0901f9014e4dda072d72b9d35aafa8cb78ff6f4b29193a9` | `273a66367154671a18a68e1b542b95d5756574d0266a1d4e9c9b5f2986cb81fc` | [#5](https://github.com/grwtsk/openai-math/issues/5), [#13](https://github.com/grwtsk/openai-math/issues/13), [PR #42](https://github.com/grwtsk/openai-math/pull/42) |
| `landau-siegel-audit-wave` | 6 | `8c1f07aecc5a62fe32eafd774a43e9c4faa0a1efa39cfb4fad99ccd174648f41` | `de55975f127f8a0c9c8c3c852e17ef91db756f30a296bb197c967c5a9963eda9` | [#40](https://github.com/grwtsk/openai-math/issues/40), [#13](https://github.com/grwtsk/openai-math/issues/13) |
| `landau-siegel-external-overlap` | 3 | `81645f05c8ed99faee758bbd740136b1fd2de936292ac7a25c7c1df2dbd58306` | `327925516429a9ed99fc806b71e049142bf1c0c03f8e9599c3bc5fc12c3171e0` | [#40](https://github.com/grwtsk/openai-math/issues/40), [#39](https://github.com/grwtsk/openai-math/issues/39), [PR #57](https://github.com/grwtsk/openai-math/pull/57) |
| `theorem-dependency-projection` | 3 | `e2e215b4249a23654695478a63a4e847f025a63ae4194c9319ccd9dc186f87dd` | `305c1dfb8b0f3e3662e27c38df2737af13ce8614656fcd87c21b373b3d6fc1c0` | [#13](https://github.com/grwtsk/openai-math/issues/13), [#22](https://github.com/grwtsk/openai-math/issues/22), [#39](https://github.com/grwtsk/openai-math/issues/39) |
| `quasi-riemann-patched-dependency-audit` | 3 | `e62b909ad7bbaac147a7081f09ab66c16eae560f00312ef6f31e50c0ddcee239` | `26f6a3c6c20f0187ea0c366131f6f2195033bd8e16bc8d809f92b754094af5ba` | [#14](https://github.com/grwtsk/openai-math/issues/14), [#22](https://github.com/grwtsk/openai-math/issues/22), [PR #54](https://github.com/grwtsk/openai-math/pull/54) |
| `quasi-riemann-import-minimization-addendum` | 3 | `77079f9348142688d701ca9228236c601cde9c63c1e4a2bac19182be8895325a` | `72b127dd5c5eb36f8e5d9018479848a4b19fd63c01a93e619d206ee5e2191918` | [#14](https://github.com/grwtsk/openai-math/issues/14), [#39](https://github.com/grwtsk/openai-math/issues/39) |
| `landau-siegel-statement-bridge` | 4 | `7699198c70284c729c439d24fc5e6b85e5651be9eb402746e15bdd4740db0592` | `c9a69c0f80611309a92fb22c51bc06e838019613b5ce357cd58b774930e91ec6` | [#40](https://github.com/grwtsk/openai-math/issues/40) |
| `analytic-landau-contradiction-review` | 2 | `956ff3ff008184765e251c1260e3a136068f113b8b401c49c204d421f89c58b2` | `129d594738af758663c45d92d7d4b473da6afd7cca71476f1bd61a1539143c8a` | [#10](https://github.com/grwtsk/openai-math/issues/10), [#40](https://github.com/grwtsk/openai-math/issues/40) |
| `comparator-closure-parser-hardening` | 6 | `fd6490c81f2f0c42986761221df479b39a2ba73ae875ebc4888b9e9a65cc9a4e` | `b2a2d1e4e8f5fc49f9c5bea31f8d4da786ffef27f6009afd820bd6963ed8c8b3` | [PR #49](https://github.com/grwtsk/openai-math/pull/49), [#12](https://github.com/grwtsk/openai-math/issues/12) |
| `metaprogramming-surface-calibration` | 6 | `337c02b6002960b08a7bc280f5fa4a0fc699dad9b372171cc8ae8d08af041eb7` | `d019d4870cb222d2554f5feb351dcb526af5fb94be31fc03f9c39a591a8d9555` | [#11](https://github.com/grwtsk/openai-math/issues/11), [PR #41](https://github.com/grwtsk/openai-math/pull/41) |
| `theorem-closure-interpretation` | 5 | `eafb7d851c949b0d746f159b05c6eca3af95981f2c7881b3fbf916440cef06d7` | `2beb37eaafacbdecdfa157cc1a240d1eb0f80ce6e9a0ef56aa91f1c6a4fb9dfd` | [#13](https://github.com/grwtsk/openai-math/issues/13), [#40](https://github.com/grwtsk/openai-math/issues/40), [PR #41](https://github.com/grwtsk/openai-math/pull/41) |

## Current status boundary

The capture preserves evidence and correction candidates; it does not silently promote them.

```text
kernel-probe correction applied to PR #42:       NO
Comparator parser hardening applied to PR #49:   NO
metaprogramming calibration applied to PR #41:   NO
Landau–Siegel statement bridge replayed:          NO
failed raw receipts rewritten:                    NO
clean-room Comparator status established:         NO
independent-kernel status established:             NO
mirror main modified:                              NO
```

The two Landau–Siegel underlying primary Lean probes completed their module builds and `#print axioms` executions, but the raw policy receipts failed because universe-instantiated foundational axiom names were compared literally. The correction package preserves that diagnosis and requires a fresh official rerun; it does not alter the historical failed receipts.

The statement-bridge source is a candidate until it is compiled in the pinned environment. The route-overlap records establish local source separation only; expanded external declaration overlap and causal independence remain unresolved.

## Verification relation

The capture was checked in two steps:

1. local reconstruction from the final segment manifest produced the exact 69,953-byte archive with SHA-256 `5664663d…a963` and successfully restored every internal artifact;
2. the committed Git tree was inspected after the corrective commit, and every capture-path Git blob identity and size matched the corresponding locally reconstructed source file.

This is repository capture and byte-integrity evidence. It is not an independent mathematical or checker review.
