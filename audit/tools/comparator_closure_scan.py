#!/usr/bin/env python3
"""Deterministic Comparator target-to-solution-closure audit.

This scanner resolves every configured Comparator target against the exact
transitive Lean import closure of its declared solution module. It is a
source-level audit, not a Lean elaborator, kernel replay, or Comparator run.
"""
from __future__ import annotations

import collections
import hashlib
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

BASE_REV = "fd4aeeb2ee4fc729c18d98444fed42fd0529eeeb"
ROOT = Path(__file__).resolve().parents[2]
LEAN = ROOT / "lean"
REPORT_ROOT = ROOT / "audit" / "reports" / f"openai-math-{BASE_REV[:12]}"

DECL_KINDS = {
    "theorem", "lemma", "def", "abbrev", "opaque", "structure", "class",
    "inductive", "axiom", "instance",
}
THEOREM_KINDS = {"theorem", "lemma"}
DEFINITION_KINDS = {"def", "abbrev", "opaque", "structure", "class", "inductive"}


@dataclass(frozen=True)
class Declaration:
    full_name: str
    token: str
    short_name: str
    kind: str
    module: str
    path: str
    line: int


@dataclass(frozen=True)
class TargetResolution:
    config: str
    target: str
    expected_role: str
    solution_module: str
    status: str
    severity: str
    candidates: tuple[Declaration, ...]
    note: str


def run_git(*args: str, binary: bool = False) -> str | bytes:
    return subprocess.check_output(
        ["git", "-C", str(ROOT), *args],
        text=not binary,
    ).strip()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def strip_lean_comments_and_strings(text: str) -> str:
    """Replace comments and strings with spaces while preserving offsets."""
    out: list[str] = []
    i = 0
    n = len(text)
    block_depth = 0
    line_comment = False
    string = False
    raw_hashes: str | None = None

    while i < n:
        c = text[i]
        nxt = text[i + 1] if i + 1 < n else ""

        if line_comment:
            if c == "\n":
                line_comment = False
                out.append("\n")
            else:
                out.append(" ")
            i += 1
            continue

        if block_depth:
            if c == "/" and nxt == "-":
                block_depth += 1
                out.extend("  ")
                i += 2
            elif c == "-" and nxt == "/":
                block_depth -= 1
                out.extend("  ")
                i += 2
            else:
                out.append("\n" if c == "\n" else " ")
                i += 1
            continue

        if raw_hashes is not None:
            close = '"' + raw_hashes
            if text.startswith(close, i):
                out.extend(" " * len(close))
                i += len(close)
                raw_hashes = None
            else:
                out.append("\n" if c == "\n" else " ")
                i += 1
            continue

        if string:
            if c == "\\" and i + 1 < n:
                out.extend("  ")
                i += 2
            elif c == '"':
                string = False
                out.append(" ")
                i += 1
            else:
                out.append("\n" if c == "\n" else " ")
                i += 1
            continue

        if c == "-" and nxt == "-":
            line_comment = True
            out.extend("  ")
            i += 2
            continue
        if c == "/" and nxt == "-":
            block_depth = 1
            out.extend("  ")
            i += 2
            continue

        raw = re.match(r'r(#+)"', text[i:])
        if raw:
            token = raw.group(0)
            raw_hashes = raw.group(1)
            out.extend(" " * len(token))
            i += len(token)
            continue

        if c == '"':
            string = True
            out.append(" ")
            i += 1
            continue

        out.append(c)
        i += 1

    return "".join(out)


def module_name_from_path(path: Path) -> str | None:
    rel = path.relative_to(LEAN).as_posix()
    if rel == "OAI.lean":
        return "OAI"
    if not rel.endswith(".lean"):
        return None
    stem = rel[:-5]
    if stem.startswith("OAI/") or stem.startswith("ComparatorChallenges/"):
        return stem.replace("/", ".")
    return None


def tracked_module_paths() -> dict[str, Path]:
    raw = run_git("ls-files", "-z", binary=True)
    assert isinstance(raw, bytes)
    result: dict[str, Path] = {}
    for item in raw.split(b"\0"):
        if not item:
            continue
        rel = item.decode("utf-8", "strict")
        if not rel.endswith(".lean"):
            continue
        path = ROOT / rel
        try:
            module = module_name_from_path(path)
        except ValueError:
            continue
        if module is not None:
            result[module] = path
    return result


def parse_imports(clean: str) -> list[str]:
    result: list[str] = []
    pattern = re.compile(r"^\s*(?:(?:public|private)\s+)?import\s+(.+?)\s*$", re.MULTILINE)
    for match in pattern.finditer(clean):
        for token in match.group(1).split():
            token = token.strip()
            if token:
                result.append(token)
    return result


def _identifier_segments(token: str) -> list[str]:
    token = token.strip()
    if token.startswith("_root_."):
        token = token[len("_root_."):]
    return [part for part in token.split(".") if part]


def parse_declarations(
    clean: str,
    *,
    module: str,
    path: str,
    relevant_short_names: set[str] | None = None,
) -> list[Declaration]:
    """Conservatively reconstruct declaration names from namespace commands.

    Exact results are accepted only when the reconstructed full name equals the
    configured target. Short-name-only matches remain review signals.
    """
    frames: list[tuple[str, str, tuple[str, ...]]] = []
    declarations: list[Declaration] = []
    current_namespace: list[str] = []

    namespace_re = re.compile(r"^\s*namespace\s+([^\s]+)\s*$")
    section_re = re.compile(r"^\s*(?:noncomputable\s+)?section(?:\s+([^\s]+))?\s*$")
    end_re = re.compile(r"^\s*end(?:\s+([^\s]+))?\s*$")
    declaration_re = re.compile(
        r"^\s*(?:@\[[^\n]*?\]\s*)*"
        r"(?:(?:private|protected|noncomputable|unsafe)\s+)*"
        r"(theorem|lemma|def|abbrev|opaque|structure|class|inductive|axiom|instance)\s+"
        r"([^\s:{(\[]+)"
    )

    def rebuild_namespace() -> None:
        current_namespace.clear()
        for kind, _label, segments in frames:
            if kind == "namespace":
                current_namespace.extend(segments)

    for line_number, line in enumerate(clean.splitlines(), 1):
        m = namespace_re.match(line)
        if m:
            token = m.group(1)
            segments = tuple(_identifier_segments(token))
            frames.append(("namespace", token, segments))
            rebuild_namespace()
            continue

        m = section_re.match(line)
        if m:
            frames.append(("section", m.group(1) or "", ()))
            continue

        m = end_re.match(line)
        if m:
            label = m.group(1)
            if frames:
                if label:
                    match_index: int | None = None
                    for index in range(len(frames) - 1, -1, -1):
                        _kind, frame_label, segments = frames[index]
                        if frame_label == label or (segments and segments[-1] == label):
                            match_index = index
                            break
                    if match_index is None:
                        frames.pop()
                    else:
                        del frames[match_index:]
                else:
                    frames.pop()
                rebuild_namespace()
            continue

        m = declaration_re.match(line)
        if not m:
            continue
        kind, token = m.group(1), m.group(2)
        if kind not in DECL_KINDS or token.startswith(":"):
            continue
        short = token.split(".")[-1]
        if relevant_short_names is not None and short not in relevant_short_names:
            continue

        if token.startswith("_root_."):
            full_segments = _identifier_segments(token)
        else:
            full_segments = [*current_namespace, *_identifier_segments(token)]
        full = ".".join(full_segments)
        declarations.append(Declaration(full, token, short, kind, module, path, line_number))

    return declarations


def compute_closure(root: str, edges: dict[str, tuple[str, ...]], known: set[str]) -> set[str]:
    seen: set[str] = set()
    stack = [root] if root in known else []
    while stack:
        module = stack.pop()
        if module in seen:
            continue
        seen.add(module)
        for dep in edges.get(module, ()):
            if dep in known and dep not in seen:
                stack.append(dep)
    return seen


def closure_digest(
    closure: Iterable[str],
    module_paths: dict[str, Path],
    file_hashes: dict[str, str],
) -> str:
    h = hashlib.sha256()
    for module in sorted(closure):
        rel = module_paths[module].relative_to(ROOT).as_posix()
        h.update(module.encode("utf-8"))
        h.update(b"\0")
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        h.update(file_hashes[module].encode("ascii"))
        h.update(b"\n")
    return h.hexdigest()


def classify_target(
    *,
    config: str,
    target: str,
    expected_role: str,
    solution_module: str,
    closure: set[str],
    full_index: dict[str, list[Declaration]],
    short_index: dict[str, list[Declaration]],
) -> TargetResolution:
    exact_global = full_index.get(target, [])
    exact_closure = [d for d in exact_global if d.module in closure]
    short = target.split(".")[-1]
    short_global = short_index.get(short, [])
    short_closure = [d for d in short_global if d.module in closure]

    if len(exact_closure) == 1:
        candidate = exact_closure[0]
        role_ok = (
            expected_role == "theorem" and candidate.kind in THEOREM_KINDS
        ) or (
            expected_role == "definition" and candidate.kind in DEFINITION_KINDS
        )
        if role_ok:
            return TargetResolution(
                config, target, expected_role, solution_module,
                "EXACT_IN_SOLUTION_CLOSURE", "none", (candidate,),
                "Exact reconstructed declaration name occurs once in the transitive solution closure.",
            )
        return TargetResolution(
            config, target, expected_role, solution_module,
            "EXACT_NAME_ROLE_MISMATCH", "high", (candidate,),
            f"Configured as {expected_role}, but lexical declaration kind is {candidate.kind}.",
        )

    if len(exact_closure) > 1:
        return TargetResolution(
            config, target, expected_role, solution_module,
            "DUPLICATE_EXACT_NAMES_IN_CLOSURE", "critical", tuple(exact_closure),
            "More than one declaration reconstructs to the configured full name.",
        )

    if exact_global:
        return TargetResolution(
            config, target, expected_role, solution_module,
            "EXACT_DECLARATION_OUTSIDE_SOLUTION_CLOSURE", "critical", tuple(exact_global),
            "The exact declaration exists in the repository but is not imported by the declared solution root.",
        )

    if len(short_closure) == 1:
        return TargetResolution(
            config, target, expected_role, solution_module,
            "UNIQUE_SHORT_NAME_IN_CLOSURE", "medium", (short_closure[0],),
            "A unique short-name candidate exists, but namespace reconstruction did not prove the full name; Lean resolution is required.",
        )

    if len(short_closure) > 1:
        return TargetResolution(
            config, target, expected_role, solution_module,
            "AMBIGUOUS_SHORT_NAME_IN_CLOSURE", "high", tuple(short_closure),
            "Multiple short-name candidates exist in the solution closure; static resolution is insufficient.",
        )

    if short_global:
        return TargetResolution(
            config, target, expected_role, solution_module,
            "SHORT_NAME_ONLY_OUTSIDE_SOLUTION_CLOSURE", "high", tuple(short_global),
            "Only short-name candidates outside the declared solution closure were found.",
        )

    return TargetResolution(
        config, target, expected_role, solution_module,
        "UNRESOLVED_IN_REPOSITORY", "critical", (),
        "No exact or short-name declaration candidate was found in tracked OAI source.",
    )


def load_configs() -> list[dict[str, Any]]:
    configs: list[dict[str, Any]] = []
    for path in sorted((LEAN / "ComparatorChallenges").glob("*.json")):
        try:
            obj = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            configs.append({
                "path": path.relative_to(ROOT).as_posix(),
                "config": path.name,
                "parse_error": str(exc),
            })
            continue
        configs.append({
            "path": path.relative_to(ROOT).as_posix(),
            "config": path.name,
            "challenge_module": obj.get("challenge_module"),
            "solution_module": obj.get("solution_module"),
            "theorem_names": obj.get("theorem_names", []),
            "definition_names": obj.get("definition_names", []),
        })
    return configs


def render_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# Comparator closure integrity scan",
        "",
        f"Frozen upstream base: `{BASE_REV}`",
        f"Audit head: `{report['identity']['head_commit']}`",
        f"Audit tree: `{report['identity']['head_tree']}`",
        "",
        "> Static source and import-closure audit only. This is not Lean elaboration,",
        "> kernel replay, Comparator execution, or a mathematical correctness certificate.",
        "",
        "## Coverage",
        "",
        f"- Comparator configurations: **{summary['config_count']:,}**",
        f"- Configured targets: **{summary['target_count']:,}**",
        f"- Tracked internal Lean modules: **{summary['module_count']:,}**",
        f"- Exact targets resolved in solution closure: **{summary['exact_in_closure']:,}**",
        f"- Policy violations: **{summary['policy_violation_count']:,}**",
        f"- Review signals: **{summary['review_signal_count']:,}**",
        "",
        "## Resolution status",
        "",
        "| Status | Count |",
        "|---|---:|",
    ]
    for status, count in sorted(summary["status_counts"].items()):
        lines.append(f"| `{status}` | {count:,} |")

    lines += ["", "## Policy violations", ""]
    if report["policy_violations"]:
        for item in report["policy_violations"][:250]:
            lines.append(
                f"- **{item['severity'].upper()}** `{item['code']}` — "
                f"`{item.get('config', '')}` — {item['detail']}"
            )
        if len(report["policy_violations"]) > 250:
            lines.append(f"- … {len(report['policy_violations']) - 250:,} additional violations are retained in JSON.")
    else:
        lines.append("No high-confidence closure-policy violation was found by this scanner.")

    lines += ["", "## Review signals", ""]
    if report["review_signals"]:
        for item in report["review_signals"][:250]:
            lines.append(
                f"- **{item['severity'].upper()}** `{item['code']}` — "
                f"`{item.get('config', '')}` — {item['detail']}"
            )
        if len(report["review_signals"]) > 250:
            lines.append(f"- … {len(report['review_signals']) - 250:,} additional signals are retained in JSON.")
    else:
        lines.append("No additional static-resolution review signal was produced.")

    lines += [
        "",
        "## Boundary",
        "",
        "An exact static match proves only that the named declaration is textually present",
        "in the transitive internal import closure. It does not prove that Lean resolves the",
        "name as expected, that the theorem has the advertised type, or that its proof uses",
        "only permitted axioms. Those require elaboration and theorem-level replay.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    REPORT_ROOT.mkdir(parents=True, exist_ok=True)
    head = str(run_git("rev-parse", "HEAD"))
    head_tree = str(run_git("rev-parse", "HEAD^{tree}"))
    base_tree = str(run_git("rev-parse", f"{BASE_REV}^{{tree}}"))
    subprocess.run(
        ["git", "-C", str(ROOT), "merge-base", "--is-ancestor", BASE_REV, head],
        check=True,
    )

    configs = load_configs()
    target_short_names: set[str] = set()
    for config in configs:
        for target in [*config.get("theorem_names", []), *config.get("definition_names", [])]:
            target_short_names.add(str(target).split(".")[-1])

    modules = tracked_module_paths()
    known = set(modules)
    edges: dict[str, tuple[str, ...]] = {}
    file_hashes: dict[str, str] = {}
    full_index: collections.defaultdict[str, list[Declaration]] = collections.defaultdict(list)
    short_index: collections.defaultdict[str, list[Declaration]] = collections.defaultdict(list)
    unresolved_internal_imports: list[dict[str, str]] = []

    for module, path in sorted(modules.items()):
        raw = path.read_bytes()
        text = raw.decode("utf-8", "strict")
        clean = strip_lean_comments_and_strings(text)
        deps = tuple(parse_imports(clean))
        edges[module] = deps
        file_hashes[module] = sha256_bytes(raw)
        rel = path.relative_to(ROOT).as_posix()
        for dep in deps:
            if (dep == "OAI" or dep.startswith("OAI.")) and dep not in known:
                unresolved_internal_imports.append({"module": module, "import": dep, "path": rel})
        for decl in parse_declarations(
            clean,
            module=module,
            path=rel,
            relevant_short_names=target_short_names,
        ):
            full_index[decl.full_name].append(decl)
            short_index[decl.short_name].append(decl)

    config_records: list[dict[str, Any]] = []
    resolutions: list[TargetResolution] = []
    policy_violations: list[dict[str, Any]] = []
    review_signals: list[dict[str, Any]] = []

    for config in configs:
        name = config["config"]
        if "parse_error" in config:
            policy_violations.append({
                "severity": "critical",
                "code": "INVALID_COMPARATOR_JSON",
                "config": name,
                "detail": config["parse_error"],
            })
            config_records.append(config)
            continue

        solution = config.get("solution_module")
        challenge = config.get("challenge_module")
        if not isinstance(challenge, str) or challenge not in known:
            policy_violations.append({
                "severity": "critical",
                "code": "MISSING_CHALLENGE_MODULE",
                "config": name,
                "detail": repr(challenge),
            })
        if not isinstance(solution, str) or solution not in known:
            policy_violations.append({
                "severity": "critical",
                "code": "MISSING_SOLUTION_MODULE",
                "config": name,
                "detail": repr(solution),
            })
            closure: set[str] = set()
        else:
            closure = compute_closure(solution, edges, known)

        challenge_modules = sorted(m for m in closure if m.startswith("ComparatorChallenges"))
        if challenge_modules:
            policy_violations.append({
                "severity": "critical",
                "code": "SOLUTION_CLOSURE_IMPORTS_CHALLENGE",
                "config": name,
                "detail": f"{solution} reaches {challenge_modules[:10]!r}",
            })

        missing_edges = sorted(
            {
                dep
                for module in closure
                for dep in edges.get(module, ())
                if (dep == "OAI" or dep.startswith("OAI.")) and dep not in known
            }
        )
        if missing_edges:
            policy_violations.append({
                "severity": "critical",
                "code": "UNRESOLVED_INTERNAL_IMPORT_IN_SOLUTION_CLOSURE",
                "config": name,
                "detail": f"{solution} has unresolved internal imports: {missing_edges[:10]!r}",
            })

        config_resolutions: list[TargetResolution] = []
        for expected_role, targets in (
            ("theorem", config.get("theorem_names", [])),
            ("definition", config.get("definition_names", [])),
        ):
            for target in targets:
                resolution = classify_target(
                    config=name,
                    target=str(target),
                    expected_role=expected_role,
                    solution_module=str(solution),
                    closure=closure,
                    full_index=full_index,
                    short_index=short_index,
                )
                resolutions.append(resolution)
                config_resolutions.append(resolution)
                if resolution.severity in {"critical", "high"}:
                    item = {
                        "severity": resolution.severity,
                        "code": resolution.status,
                        "config": name,
                        "detail": f"{resolution.target}: {resolution.note}",
                    }
                    if resolution.severity == "critical":
                        policy_violations.append(item)
                    else:
                        review_signals.append(item)
                elif resolution.severity != "none":
                    review_signals.append({
                        "severity": resolution.severity,
                        "code": resolution.status,
                        "config": name,
                        "detail": f"{resolution.target}: {resolution.note}",
                    })

        config_records.append({
            **config,
            "solution_closure_module_count": len(closure),
            "solution_closure_sha256": closure_digest(closure, modules, file_hashes) if closure else None,
            "solution_closure_challenge_modules": challenge_modules,
            "solution_closure_missing_internal_imports": missing_edges,
            "target_resolutions": [asdict(r) for r in config_resolutions],
            "challenge_module_present": isinstance(challenge, str) and challenge in known,
        })

    status_counts = collections.Counter(r.status for r in resolutions)
    exact_count = status_counts.get("EXACT_IN_SOLUTION_CLOSURE", 0)
    report = {
        "schema_version": "ComparatorClosureIntegrity/1",
        "identity": {
            "base_revision": BASE_REV,
            "base_tree": base_tree,
            "head_commit": head,
            "head_tree": head_tree,
            "scanner_path": str(Path(__file__).relative_to(ROOT)),
            "scanner_sha256": sha256_bytes(Path(__file__).read_bytes()),
        },
        "summary": {
            "config_count": len(configs),
            "target_count": len(resolutions),
            "module_count": len(modules),
            "exact_in_closure": exact_count,
            "status_counts": dict(sorted(status_counts.items())),
            "policy_violation_count": len(policy_violations),
            "review_signal_count": len(review_signals),
            "unresolved_internal_import_count": len(unresolved_internal_imports),
        },
        "unresolved_internal_imports": unresolved_internal_imports,
        "policy_violations": policy_violations,
        "review_signals": review_signals,
        "configs": config_records,
        "limits": [
            "Static lexical namespace reconstruction is conservative and does not replace Lean name resolution.",
            "Import closure covers tracked OAI and Comparator modules; external dependency closures require separate receipts.",
            "Exact name presence does not establish theorem type, proof correctness, or transitive axioms.",
        ],
    }

    json_path = REPORT_ROOT / "comparator-closure-integrity.json"
    markdown_path = REPORT_ROOT / "comparator-closure-integrity.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    receipt = {
        "schema_version": "ComparatorClosureReceipt/1",
        "report_json": str(json_path.relative_to(ROOT)),
        "report_json_sha256": sha256_bytes(json_path.read_bytes()),
        "report_markdown": str(markdown_path.relative_to(ROOT)),
        "report_markdown_sha256": sha256_bytes(markdown_path.read_bytes()),
    }
    receipt_path = REPORT_ROOT / "comparator-closure-receipt.json"
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(json.dumps({
        **report["summary"],
        **receipt,
    }, indent=2, sort_keys=True))
    return 1 if policy_violations else 0


if __name__ == "__main__":
    sys.exit(main())
