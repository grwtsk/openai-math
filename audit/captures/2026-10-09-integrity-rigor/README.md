# Integrity and rigor audit capture — 2026-10-09

This directory gives durable Git custody to the audit state developed after the first OpenAI-math integrity wave.

**Effect class:** `AUDIT_ONLY_DO_NOT_MERGE_TO_MIRROR_MAIN`

The fork's `main` branch remains the exact mirror of `openai/math@fd4aeeb2ee4fc729c18d98444fed42fd0529eeeb`. This capture belongs on an audit branch. It contains evidence, interpretations, correction proposals, hostile reviews, and one unreplayed Lean bridge candidate. It does not alter the mirrored mathematics and does not promote provisional results to accepted proof evidence.

## Contents

- `CAPTURE_MANIFEST.json` — exact source-package and workflow-artifact identities.
- `evidence.json` / `EVIDENCE.md` — machine-readable and accessible consolidated evidence.
- `LandauSiegelStatementBridge.lean` — unreplayed statement-shape bridge candidate.
- `kernel-probe-v2.patch` — repairs universe-polymorphic axiom-name comparison and receipt hygiene.
- `comparator-closure-v2.patch` — hardens visibility and Lean lexical-block handling.
- `metaprogramming-classification-v2.patch` — separates imports, direct API use, and executed `run_tac`.
- `PATCH_VALIDATION.md` — original rationale and hostile-test outcomes.
- `capture_workflow_artifacts.py` and the associated workflow — verify and preserve expiring raw workflow artifacts as a fork-side audit prerelease without adding large generated data to ordinary Git history.

## Supersession rule

Nothing here silently rewrites an earlier workflow outcome. A correction must cite the earlier receipt, preserve its bytes, apply the reviewed tool change, rerun the exact target, and issue a new receipt linked by an explicit supersession edge.
