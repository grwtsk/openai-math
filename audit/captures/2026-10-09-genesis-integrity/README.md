# Genesis integrity evidence capture — 2026-10-09

> **No system is perfect, but, we *can* try.**

This branch preserves the audit evidence and correction packages generated during the Genesis review of `openai/math@fd4aeeb2ee4fc729c18d98444fed42fd0529eeeb` that were previously present only in transient sandbox files.

## Hard boundary

This is **audit-only**. The fork's `main` branch remains the byte-identical upstream mirror. Do not merge this evidence archive into mirror `main`.

The archive contains the receipt-parser correction, joined Landau–Siegel receipts, external-overlap correction, dependency projection, quasi-Riemann dependency reviews, statement-bridge candidate, contradiction/subsingleton review, Comparator parser hardening, metaprogramming calibration, and theorem-closure interpretation records.

The original failed receipts are preserved. Nothing here retroactively converts a failed policy gate into a green official receipt. The corrected primary-kernel probes require a fresh run. The Lean statement bridge remains unreplayed. No clean-room Comparator, independent-kernel, peer-review, originality, independence, or upstream-acceptance claim is made.

## Reconstruct

```sh
python3 reconstruct_archive.py --output genesis-integrity-capture.tar.gz
sha256sum genesis-integrity-capture.tar.gz
# expected: 5664663da5c4ca437602c9d5e972f06c9cffac7aae7fda775ea05ba81b83a963

tar -xzf genesis-integrity-capture.tar.gz
cd genesis-integrity-capture
python3 reconstruct.py --output reconstructed
```

`capture-manifest.json` binds each base64 archive segment and the reconstructed archive digest. The archive's internal `capture-manifest.json` binds every embedded package envelope and each extracted artifact byte.
