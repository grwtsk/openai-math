#!/usr/bin/env python3
"""Measure formal-source overlap between the two Landau–Siegel proof routes.

This is a deterministic static import-closure audit for the frozen OpenAI math
snapshot. It does not establish mathematical, causal, or implementation-level
independence and does not replace Lean elaboration or kernel replay.
"""
from __future__ import annotations

import collections
import hashlib
import json
import os
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

GEOMETRIC_ROOT = "OAI.NumberTheory.SiegelZeros.Conclusions.Theorem"
ANALYTIC_ROOT = "OAI.NumberTheory.SiegelZeros.Characters.DirichletRealZeroBoundProof"
GEOMETRIC_TARGET = "OAI.SiegelZeros.WeightedTorusJets.exists_absolute_real_zero_gap"
ANALYTIC_TARGET = "OAI.SiegelZeros.WeightedTorusJets.dirichletRealZeroBound_proof"

DECL_KINDS = {
    "theorem", "lemma", "def", "abbrev", "opaque", "structure", "class",
    "inductive", "axiom", "instance",
}


@dataclass(frozen=True)
class Declaration:
    full_name: str
    kind: str
    module: str
    path: str
    line: int


@dataclass(frozen=True)
class RouteRecord:
    name: str
    root_module: str
    target: str
    closure_module_count: int
    closure_sha256: str
    internal_modules: tuple[str, ...]
    external_imports: tuple[str, ...]
    unresolved_internal_imports: tuple[str, ...]
    root_declarations: tuple[Declaration, ...]
    target_declared_in_root: bool
    target_declared_in_closure: bool
    cross_route_root_in_closure: bool
    other_target_full_name_references: tuple[str, ...]
    other_target_short_name_references: tuple[str, ...]


def run_git(*args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(ROOT), *args],
        text=True,
        stderr=subprocess.PIPE,
    ).strip()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def module_to_path(module: str, lean_root: Path = LEAN) -> Path:
    return lean_root / (module.replace(".", "/") + ".lean")


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


def parse_imports(clean: str) -> list[str]:
    result: list[str] = []
    pattern = re.compile(
        r"^\s*(?:(?:public|private)\s+)?import\s+(.+?)\s*$",
        re.MULTILINE,
    )
    for match in pattern.finditer(clean):
        for token in match.group(1).split():
            token = token.strip()
            if token:
                result.append(token)
    return result


def identifier_segments(token: str) -> list[str]:
    token = token.strip()
    if token.startswith("_root_."):
        token = token[len("_root_."):]
    return [part for part in token.split(".") if part]


def parse_declarations(clean: str, *, module: str, path: str) -> list[Declaration]:
    """Conservatively reconstruct top-level declaration names."""
    frames: list[tuple[str, str, tuple[str, ...]]] = []
    namespace: list[str] = []
    result: list[Declaration] = []

    namespace_re = re.compile(r"^\s*namespace\s+([^\s]+)\s*$")
    section_re = re.compile(r"^\s*(?:noncomputable\s+)?section(?:\s+([^\s]+))?\s*$")
    end_re = re.compile(r"^\s*end(?:\s+([^\s]+))?\s*$")
    decl_re = re.compile(
        r"^\s*(?:@\[[^\n]*?\]\s*)*"
        r"(?:(?:private|protected|noncomputable|unsafe)\s+)*"
        r"(theorem|lemma|def|abbrev|opaque|structure|class|inductive|axiom|instance)\s+"
        r"([^\s:{(\[]+)"
    )

    def rebuild_namespace() -> None:
        namespace.clear()
        for kind, _label, segments in frames:
            if kind == "namespace":
                namespace.extend(segments)

    for line_no, line in enumerate(clean.splitlines(), 1):
        match = namespace_re.match(line)
        if match:
            label = match.group(1)
            segments = tuple(identifier_segments(label))
            frames.append(("namespace", label, segments))
            rebuild_namespace()
            continue

        match = section_re.match(line)
        if match:
            frames.append(("section", match.group(1) or "", ()))
            continue

        match = end_re.match(line)
        if match:
            label = match.group(1)
            if frames:
                if label:
                    index: int | None = None
                    for i in range(len(frames) - 1, -1, -1):
                        _kind, frame_label, segments = frames[i]
                        if frame_label == label or (segments and segments[-1] == label):
                            index = i
                            break
                    if index is None:
                        frames.pop()
                    else:
                        del frames[index:]
                else:
                    frames.pop()
                rebuild_namespace()
            continue

        match = decl_re.match(line)
        if not match:
            continue
        kind, token = match.group(1), match.group(2)
        if kind not in DECL_KINDS or token.startswith(":"):
            continue
        if token.startswith("_root_."):
            full = ".".join(identifier_segments(token))
        else:
            full = ".".join([*namespace, *identifier_segments(token)])
        result.append(Declaration(full, kind, module, path, line_no))

    return result


def crawl_closure(root_module: str, lean_root: Path = LEAN) -> dict[str, Any]:
    queue = collections.deque([root_module])
    modules: dict[str, dict[str, Any]] = {}
    external: set[str] = set()
    unresolved_internal: set[str] = set()

    while queue:
        module = queue.popleft()
        if module in modules:
            continue
        path = module_to_path(module, lean_root)
        if not path.exists():
            if module == "OAI" or module.startswith("OAI."):
                unresolved_internal.add(module)
            else:
                external.add(module)
            continue

        raw = path.read_bytes()
        text = raw.decode("utf-8", "strict")
        clean = strip_lean_comments_and_strings(text)
        imports = parse_imports(clean)
        rel = path.relative_to(lean_root.parent).as_posix() if lean_root.parent in path.parents else path.as_posix()
        modules[module] = {
            "module": module,
            "path": rel,
            "sha256": sha256_bytes(raw),
            "clean": clean,
            "imports": tuple(imports),
            "declarations": tuple(parse_declarations(clean, module=module, path=rel)),
        }
        for imported in imports:
            if imported == "OAI" or imported.startswith("OAI."):
                if imported not in modules:
                    queue.append(imported)
            else:
                external.add(imported)

    return {
        "modules": modules,
        "external_imports": external,
        "unresolved_internal_imports": unresolved_internal,
    }


def closure_digest(modules: dict[str, dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for module in sorted(modules):
        record = modules[module]
        digest.update(module.encode("utf-8"))
        digest.update(b"\0")
        digest.update(record["path"].encode("utf-8"))
        digest.update(b"\0")
        digest.update(record["sha256"].encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def reference_locations(
    modules: dict[str, dict[str, Any]],
    token: str,
) -> tuple[str, ...]:
    hits: list[str] = []
    pattern = re.compile(re.escape(token))
    for module, record in sorted(modules.items()):
        clean = record["clean"]
        for match in pattern.finditer(clean):
            line = clean.count("\n", 0, match.start()) + 1
            hits.append(f"{record['path']}:{line}")
    return tuple(hits)


def make_route_record(
    *,
    name: str,
    root_module: str,
    target: str,
    other_root: str,
    other_target: str,
    crawl: dict[str, Any],
) -> RouteRecord:
    modules: dict[str, dict[str, Any]] = crawl["modules"]
    root_record = modules.get(root_module)
    root_declarations = tuple(root_record["declarations"]) if root_record else ()
    all_declarations = [
        declaration
        for record in modules.values()
        for declaration in record["declarations"]
    ]
    other_short = other_target.split(".")[-1]
    return RouteRecord(
        name=name,
        root_module=root_module,
        target=target,
        closure_module_count=len(modules),
        closure_sha256=closure_digest(modules),
        internal_modules=tuple(sorted(modules)),
        external_imports=tuple(sorted(crawl["external_imports"])),
        unresolved_internal_imports=tuple(sorted(crawl["unresolved_internal_imports"])),
        root_declarations=root_declarations,
        target_declared_in_root=any(d.full_name == target for d in root_declarations),
        target_declared_in_closure=any(d.full_name == target for d in all_declarations),
        cross_route_root_in_closure=other_root in modules,
        other_target_full_name_references=reference_locations(modules, other_target),
        other_target_short_name_references=reference_locations(modules, other_short),
    )


def prefix_counts(imports: Iterable[str]) -> dict[str, int]:
    counts: collections.Counter[str] = collections.Counter()
    for module in imports:
        counts[module.split(".", 1)[0]] += 1
    return dict(sorted(counts.items()))


def render_markdown(report: dict[str, Any]) -> str:
    geometric = report["routes"]["geometric"]
    analytic = report["routes"]["analytic"]
    comparison = report["comparison"]
    lines = [
        "# Landau–Siegel proof-route closure audit",
        "",
        f"Frozen upstream base: `{BASE_REV}`",
        f"Audit head: `{report['identity']['head_commit']}`",
        f"Audit tree: `{report['identity']['head_tree']}`",
        "",
        "> This measures formal source structure only. It does not establish",
        "> mathematical, causal, model, or implementation-level independence.",
        "",
        "## Route roots",
        "",
        "| Route | Root module | Selected theorem | Internal modules |",
        "|---|---|---|---:|",
        f"| Geometric/Bezout | `{geometric['root_module']}` | `{geometric['target']}` | {geometric['closure_module_count']:,} |",
        f"| Analytic/sequence | `{analytic['root_module']}` | `{analytic['target']}` | {analytic['closure_module_count']:,} |",
        "",
        "## Closure comparison",
        "",
        f"- Shared internal modules: **{comparison['shared_module_count']:,}**",
        f"- Geometric-only modules: **{comparison['geometric_only_module_count']:,}**",
        f"- Analytic-only modules: **{comparison['analytic_only_module_count']:,}**",
        f"- Jaccard overlap: **{comparison['jaccard_overlap']:.6f}**",
        f"- Geometric closure reaches analytic root: `{geometric['cross_route_root_in_closure']}`",
        f"- Analytic closure reaches geometric root: `{analytic['cross_route_root_in_closure']}`",
        f"- Shared external import names: **{comparison['shared_external_import_count']:,}**",
        "",
        "## Target resolution",
        "",
        f"- Geometric target declared in root: `{geometric['target_declared_in_root']}`",
        f"- Analytic target declared in root: `{analytic['target_declared_in_root']}`",
        f"- Geometric closure references analytic full target: `{bool(geometric['other_target_full_name_references'])}`",
        f"- Analytic closure references geometric full target: `{bool(analytic['other_target_full_name_references'])}`",
        "",
        "## Policy result",
        "",
    ]
    if report["policy_violations"]:
        for item in report["policy_violations"]:
            lines.append(f"- **{item['code']}**: {item['detail']}")
    else:
        lines.append("No direct final-route import or unresolved internal import was detected by this scanner.")
    lines += ["", "## Review signals", ""]
    if report["review_signals"]:
        for item in report["review_signals"]:
            lines.append(f"- **{item['code']}**: {item['detail']}")
    else:
        lines.append("No additional lexical cross-route reference was detected.")
    lines += [
        "",
        "## Boundary",
        "",
        "Structural separation permits separate theorem receipts. It does not show that",
        "the arguments are mathematically independent, that shared lemmas are correct,",
        "that one route was discovered without knowledge of the other, or that either route",
        "has passed Comparator or an independent kernel.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    os.chdir(ROOT)
    REPORT_ROOT.mkdir(parents=True, exist_ok=True)

    head = run_git("rev-parse", "HEAD")
    head_tree = run_git("rev-parse", "HEAD^{tree}")
    base_tree = run_git("rev-parse", f"{BASE_REV}^{{tree}}")
    subprocess.run(
        ["git", "-C", str(ROOT), "merge-base", "--is-ancestor", BASE_REV, head],
        check=True,
    )

    geometric_crawl = crawl_closure(GEOMETRIC_ROOT)
    analytic_crawl = crawl_closure(ANALYTIC_ROOT)
    geometric = make_route_record(
        name="geometric",
        root_module=GEOMETRIC_ROOT,
        target=GEOMETRIC_TARGET,
        other_root=ANALYTIC_ROOT,
        other_target=ANALYTIC_TARGET,
        crawl=geometric_crawl,
    )
    analytic = make_route_record(
        name="analytic",
        root_module=ANALYTIC_ROOT,
        target=ANALYTIC_TARGET,
        other_root=GEOMETRIC_ROOT,
        other_target=GEOMETRIC_TARGET,
        crawl=analytic_crawl,
    )

    geometric_modules = set(geometric.internal_modules)
    analytic_modules = set(analytic.internal_modules)
    shared = geometric_modules & analytic_modules
    union = geometric_modules | analytic_modules
    geometric_external = set(geometric.external_imports)
    analytic_external = set(analytic.external_imports)

    policy_violations: list[dict[str, str]] = []
    review_signals: list[dict[str, str]] = []

    for route in (geometric, analytic):
        if not route.target_declared_in_root:
            policy_violations.append({
                "code": "TARGET_NOT_DECLARED_IN_ROUTE_ROOT",
                "detail": f"{route.target} was not reconstructed in {route.root_module}",
            })
        if route.unresolved_internal_imports:
            policy_violations.append({
                "code": "UNRESOLVED_INTERNAL_IMPORT",
                "detail": f"{route.name}: {route.unresolved_internal_imports!r}",
            })
        if route.cross_route_root_in_closure:
            policy_violations.append({
                "code": "FINAL_ROUTE_CROSS_IMPORT",
                "detail": f"{route.name} closure imports the other final route root",
            })
        if route.other_target_full_name_references:
            review_signals.append({
                "code": "OTHER_FINAL_TARGET_FULL_NAME_REFERENCE",
                "detail": f"{route.name}: {route.other_target_full_name_references!r}",
            })
        short_only = sorted(
            set(route.other_target_short_name_references)
            - set(route.other_target_full_name_references)
        )
        if short_only:
            review_signals.append({
                "code": "OTHER_FINAL_TARGET_SHORT_NAME_REFERENCE",
                "detail": f"{route.name}: {short_only!r}",
            })

    if not geometric_modules - analytic_modules:
        review_signals.append({
            "code": "NO_GEOMETRIC_ONLY_MODULES",
            "detail": "The geometric closure is contained in the analytic closure.",
        })
    if not analytic_modules - geometric_modules:
        review_signals.append({
            "code": "NO_ANALYTIC_ONLY_MODULES",
            "detail": "The analytic closure is contained in the geometric closure.",
        })

    comparison = {
        "shared_module_count": len(shared),
        "geometric_only_module_count": len(geometric_modules - analytic_modules),
        "analytic_only_module_count": len(analytic_modules - geometric_modules),
        "union_module_count": len(union),
        "jaccard_overlap": len(shared) / len(union) if union else 1.0,
        "shared_modules": sorted(shared),
        "geometric_only_modules": sorted(geometric_modules - analytic_modules),
        "analytic_only_modules": sorted(analytic_modules - geometric_modules),
        "shared_external_import_count": len(geometric_external & analytic_external),
        "shared_external_imports": sorted(geometric_external & analytic_external),
        "geometric_only_external_imports": sorted(geometric_external - analytic_external),
        "analytic_only_external_imports": sorted(analytic_external - geometric_external),
        "geometric_external_prefix_counts": prefix_counts(geometric.external_imports),
        "analytic_external_prefix_counts": prefix_counts(analytic.external_imports),
        "prime_number_theorem_and_in_geometric": any(
            item.startswith("PrimeNumberTheoremAnd") for item in geometric.external_imports
        ),
        "prime_number_theorem_and_in_analytic": any(
            item.startswith("PrimeNumberTheoremAnd") for item in analytic.external_imports
        ),
    }

    report = {
        "schema_version": "SiegelRouteClosureAudit/1",
        "identity": {
            "base_revision": BASE_REV,
            "base_tree": base_tree,
            "head_commit": head,
            "head_tree": head_tree,
            "scanner_path": str(Path(__file__).relative_to(ROOT)),
            "scanner_sha256": sha256_bytes(Path(__file__).read_bytes()),
        },
        "classification": "STRUCTURAL_SEPARATION_AUDIT_ONLY",
        "routes": {
            "geometric": asdict(geometric),
            "analytic": asdict(analytic),
        },
        "comparison": comparison,
        "policy_violations": policy_violations,
        "review_signals": review_signals,
        "limits": [
            "Static source and import-closure analysis only.",
            "Does not establish mathematical, causal, model, or implementation-level independence.",
            "Does not elaborate Lean, print axioms, execute Comparator, or replay an independent kernel.",
            "External dependency closures and patched-tree identities require separate receipts.",
        ],
    }

    json_path = REPORT_ROOT / "siegel-route-closure.json"
    md_path = REPORT_ROOT / "siegel-route-closure.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    receipt = {
        "schema_version": "SiegelRouteClosureReceipt/1",
        "report_json": str(json_path.relative_to(ROOT)),
        "report_json_sha256": sha256_bytes(json_path.read_bytes()),
        "report_markdown": str(md_path.relative_to(ROOT)),
        "report_markdown_sha256": sha256_bytes(md_path.read_bytes()),
    }
    receipt_path = REPORT_ROOT / "siegel-route-closure-receipt.json"
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(json.dumps({
        **receipt,
        "geometric_modules": geometric.closure_module_count,
        "analytic_modules": analytic.closure_module_count,
        "shared_modules": len(shared),
        "policy_violations": len(policy_violations),
        "review_signals": len(review_signals),
    }, indent=2, sort_keys=True))
    return 1 if policy_violations else 0


if __name__ == "__main__":
    sys.exit(main())
