#!/usr/bin/env python3
"""Fork-side, source-bound selection-integrity research harness (stdlib only).

PUBLIC analysis: catalogue-order morphology, NOT original model/event order.
CONTROLLED experiment: fully disclosed synthetic generator/filter factorial, NOT OpenAI internals.

Usage:
  python3 experiment.py --mode all --root /path/to/checkout --out results.json
  python3 experiment.py --mode synthetic --out results.json
  python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import random
import re
from collections import Counter
from pathlib import Path

SOURCE_SHA = {
    "CONTENTS.md": "2c68c086fff36a5806c936ad1659cf1a8d0b6dd9",
    "README.md": "50feb63d396138f30dc1ff1e0af121d0263bf5a3",
}
SEED = 20261009
COUNT_PATTERN = re.compile(r"\*\*(\d{3})\.\s")
PAPER_PATTERN = re.compile(r"&emsp;\[[^\]]+\]\(preprints/")
TRACE_PATTERN = re.compile(r"\|\s*(\d{3})\s*\|\s*\[")


def git_blob_sha(content: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(content)).encode() + b"\0" + content).hexdigest()


def parse_catalog(contents: str, readme: str) -> tuple[list[int], list[int], list[int]]:
    markers = list(COUNT_PATTERN.finditer(contents))
    ids = [int(m.group(1)) for m in markers]
    counts = [len(PAPER_PATTERN.findall(contents[m.start():markers[i + 1].start() if i + 1 < len(markers) else len(contents)])) for i, m in enumerate(markers)]
    trace = [int(x) for x in TRACE_PATTERN.findall(readme)]
    if not ids or sorted(ids) != ids or len(set(ids)) != len(ids) or not all(n > 0 for n in counts):
        raise ValueError("Catalogue not parseable under pinned schema")
    if len(trace) != len(set(trace)) or any(x not in ids for x in trace):
        raise ValueError("Reasoning IDs inconsistent with catalogue")
    return ids, counts, trace


def load_catalog(root: Path) -> tuple[list[int], list[int], list[int]]:
    parts = {}
    for path, expected in SOURCE_SHA.items():
        raw = (root / path).read_bytes()
        actual = git_blob_sha(raw)
        if actual != expected:
            raise ValueError(f"SOURCE_CHANGED: {path}, expected {expected}, got {actual}")
        parts[path] = raw.decode("utf-8")
    return parse_catalog(parts["CONTENTS.md"], parts["README.md"])


def exact_hypergeom_tail(N: int, K: int, n: int, x: int) -> float:
    denom = math.comb(N, n)
    return sum(math.comb(K, j) * math.comb(N - K, n - j)
               for j in range(x, min(K, n) + 1)
               if 0 <= n - j <= N - K) / denom


def signed_cusum(a: list[int]) -> tuple[float, int, float, float]:
    mean = sum(a) / len(a)
    s = 0.0
    maximum, index, direction = 0.0, 0, 0.0
    for i, v in enumerate(a, 1):
        s += v - mean
        if abs(s) > maximum:
            maximum, index, direction = abs(s), i, s
    return maximum, index, direction, mean


def catalogue_audit(ids: list[int], counts: list[int], traces: list[int], *, permutations: int = 5000, seed: int = SEED) -> dict:
    """All p-values CONDITIONAL on catalogue ordering/exchangeability assumptions."""
    if len(ids) != len(counts) or not traces or not set(traces).issubset(set(ids)):
        raise ValueError("Invalid public data")
    N, n = len(ids), len(traces)
    chosen = set(traces)
    selected_mean = sum(v for i, v in zip(ids, counts) if i in chosen) / n
    overall_mean = sum(counts) / N
    digit_K = [sum(str(d) in str(id_) for id_ in ids) for d in range(10)]
    digit_x = [sum(str(d) in str(id_) for id_ in traces) for d in range(10)]
    p_digit = [exact_hypergeom_tail(N, digit_K[d], n, digit_x[d]) for d in range(10)]
    observed_min = min(p_digit)
    observed_cusum, point, direction, _ = signed_cusum(counts)

    # A finite randomization test using the MINIMUM of all ten digit tests.
    # This controls only the ten-digit search family; all exploratory OEIS searches
    # and post-hoc choice of tests remain uncorrected.
    rng = random.Random(seed)
    n_min_extreme = 0
    n_cusum_extreme = 0
    n_mean_extreme = 0
    sum_counts = sum(counts)
    # Random subsets are sampled without replacement; sample is unordered.
    for _ in range(permutations):
        sample = rng.sample(range(N), n)
        sample_ids = [ids[i] for i in sample]
        minp = min(exact_hypergeom_tail(N, digit_K[d], n, sum(str(d) in str(k) for k in sample_ids)) for d in range(10))
        n_min_extreme += minp <= observed_min + 1e-14
        sample_mean = sum(counts[i] for i in sample) / n
        n_mean_extreme += abs(sample_mean - overall_mean) >= abs(selected_mean - overall_mean) - 1e-14
        shuffled = counts.copy()
        rng.shuffle(shuffled)
        n_cusum_extreme += signed_cusum(shuffled)[0] >= observed_cusum - 1e-14
    p_fwer = (n_min_extreme + 1) / (permutations + 1)
    p_cusum = (n_cusum_extreme + 1) / (permutations + 1)
    p_mean = (n_mean_extreme + 1) / (permutations + 1)
    missing = sorted(set(range(1, max(ids) + 1)) - set(ids))
    return {
        "evidence_grade": "PUBLIC_CATALOGUE_ONLY_NOT_INTERNAL_SELECTION",
        "source_revision": "openai/math@fd4aeeb2ee4fc729c18d98444fed42fd0529eeeb",
        "source_blob_shas": SOURCE_SHA,
        "families": N, "manuscripts": sum_counts,
        "missing_family_identifiers": missing,
        "reasoning_family_identifiers": traces,
        "reasoning_sample_n": n,
        "manuscript_count_distribution": dict(sorted(Counter(counts).items())),
        "digit_search": {
            "selected_digit": int(min(range(10), key=lambda i: p_digit[i])),
            "digit7_exact_overlap": digit_x[7],
            "digit7_population_count": digit_K[7],
            "digit7_nominal_one_sided_hypergeom_p": p_digit[7],
            "minimum_nominal_digit_p": observed_min,
            "ten_digit_search_familywise_permutation_p": p_fwer,
            "permutations": permutations,
            "interpretation": "EXPLORATORY_ONLY: digit/sequence chosen after viewing data; catalogue indices not trial order",
        },
        "manuscripts_per_family": {
            "reasoning_selected_mean": selected_mean,
            "all_families_mean": overall_mean,
            "difference": selected_mean - overall_mean,
            "two_sided_uniform_subset_permutation_p": p_mean,
        },
        "catalogue_order_cusum": {
            "max_abs_centered_partial_sum": observed_cusum,
            "peak_index_in_catalogue": point,
            "direction_at_peak": direction,
            "permutation_p_under_exchangeable_order": p_cusum,
            "permutations": permutations,
            "interpretation": "CATALOGUE_ORDER_ONLY: not chronological and grouped by discipline; exchangeability is doubtful",
        },
        "internal_selection_process_identifiable": False,
    }


def mcnemar(a: list[bool], b: list[bool]) -> dict:
    if len(a) != len(b) or not a:
        raise ValueError("Nonempty paired data required")
    ctrl_yes_variant_no = sum(x and not y for x, y in zip(a, b))
    ctrl_no_variant_yes = sum(not x and y for x, y in zip(a, b))
    t = ctrl_yes_variant_no + ctrl_no_variant_yes
    if t:
        # Exact two-sided binomial test conditional on discordants.
        smaller = min(ctrl_yes_variant_no, ctrl_no_variant_yes)
        p = min(1.0, 2 * sum(math.comb(t, k) for k in range(smaller + 1)) / (2 ** t))
    else:
        p = 1.0
    return {
        "control_accept_variant_reject": ctrl_yes_variant_no,
        "control_reject_variant_accept": ctrl_no_variant_yes,
        "discordant_pairs": t,
        "paired_variant_minus_control_acceptance": (sum(b) - sum(a)) / len(a),
        "exact_mcnemar_two_sided_p": p,
        "disagreement_rate": t / len(a),
    }


def simulate(*, n: int = 1200, seed: int = SEED, filter_bias: float = 0.08, generator_bias: float = 0.08) -> dict:
    """Paired 2x2 crossover; deterministic fixture generator; deliberately injected effects.

    Synthetic semantic-equivalence label means only the scoring *ground truth* is
    fixed across renderings. This is NOT a formal equivalence proof for natural-language mathematics.
    """
    rng = random.Random(seed)
    canonical, alternate = [], []
    # The latent score and pair-specific generator noise are frozen and reused
    # across filter arms; the treatment rendering is randomized within each pair.
    assignments = []
    for _ in range(n):
        u = rng.random()
        canonical.append(u + rng.gauss(0, 0.07))
        alternate.append(u + rng.gauss(0, 0.07))
        assignments.append(rng.randrange(2))
    threshold = 0.5
    # Generator G0, filter F0: no intentionally introduced asymmetry.
    base_c = [v >= threshold for v in canonical]
    base_v = [v >= threshold for v in alternate]
    # Frozen G0 scores, alternative F1 applies explicit presentation bias.
    filt_c = base_c
    filt_v = [v >= threshold + filter_bias for v in alternate]
    # Alternative G1 changes treatment generator scores under SAME F0 filter.
    gen_v = [v - generator_bias >= threshold for v in alternate]
    # G1 + F1 interaction for factorial accounting (no inference from marginal alone).
    both_v = [v - generator_bias >= threshold + filter_bias for v in alternate]
    out = {
        "evidence_grade": "SYNTHETIC_CONTROLLED_SIMULATION_NOT_OPENAI_MODEL",
        "n_paired_tasks": n,
        "random_seed": seed,
        "randomized_presentation_order_balanced": [assignments.count(0), assignments.count(1)],
        "fixed_base_filter_threshold": threshold,
        "injected_filter_presentation_penalty": filter_bias,
        "injected_generator_score_penalty": generator_bias,
        "no_injected_effect_G0_F0": mcnemar(base_c, base_v),
        "filter_only_G0_F1": mcnemar(filt_c, filt_v),
        "generator_only_G1_F0": mcnemar(base_c, gen_v),
        "both_G1_F1": mcnemar(base_c, both_v),
        "filter_attribution_control": {
            "max_absolute_generator_score_change_between_filter_arms": 0.0,
            "filter_only_disagreement_delta": (sum(x != y for x, y in zip(filt_c, filt_v)) - sum(x != y for x, y in zip(base_c, base_v))) / n,
        },
        "interpretation": "Positive controls demonstrate detection and source attribution by frozen scores; not a measurement of any live model or filter",
    }
    return out


def calibration(*, seeds: int = 36, n_per_seed: int = 600) -> dict:
    """Repeated paired null and injected-effect controls: preregister alpha=0.01."""
    false_alerts = 0
    injected_detections = 0
    for s in range(seeds):
        d = simulate(n=n_per_seed, seed=SEED + s, filter_bias=0.08, generator_bias=0.08)
        false_alerts += d["no_injected_effect_G0_F0"]["exact_mcnemar_two_sided_p"] < 0.01
        injected_detections += (d["filter_only_G0_F1"]["exact_mcnemar_two_sided_p"] < 0.01 and
                                d["filter_only_G0_F1"]["paired_variant_minus_control_acceptance"] < 0)
    return {"seed_replicates": seeds, "tasks_per_seed": n_per_seed,
            "decision_alpha": 0.01, "null_false_alerts": false_alerts,
            "injected_filter_detections": injected_detections,
            "limitations": "Simulated calibration only, no real false-positive guarantee under model drift"}


def run(mode: str, root: Path, permutations: int, *, seed: int = SEED) -> dict:
    result = {"schema": "SelectionIntegrityExperiment/1", "seed": seed,
              "research_question": "Can candidate/filter sensitivity be measured and separated from publication-only structure?",
              "explicit_limit": "No original internal OpenAI attempts, checkpoint labels, variants, reward scores, or filter decisions are published here."}
    if mode in {"all", "synthetic"}:
        result["synthetic_factorial"] = simulate(seed=seed)
        result["synthetic_calibration"] = calibration()
    if mode in {"all", "catalog"}:
        ids, counts, traces = load_catalog(root)
        result["public_catalogue"] = catalogue_audit(ids, counts, traces, permutations=permutations, seed=seed)
    return result


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=("all", "catalog", "synthetic"), default="all")
    ap.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    ap.add_argument("--permutations", type=int, default=5000)
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    if args.permutations < 1:
        ap.error("--permutations must be positive")
    result = run(args.mode, args.root, args.permutations, seed=args.seed)
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.out:
        args.out.write_text(rendered, encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
