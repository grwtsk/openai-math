#!/usr/bin/env python3
"""GenesisRigorScan/2: deterministic static audit of the checked-out Git tree.

The report separates high-confidence policy violations from review signals.
It does not claim theorem correctness, novelty, priority, or authorship.
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
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
LEAN = ROOT / "lean"
OUT = ROOT / "audit" / "results"
OUT.mkdir(parents=True, exist_ok=True)


def run(*args: str) -> str:
    return subprocess.check_output(args, cwd=ROOT, text=True).strip()


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tracked() -> list[Path]:
    raw = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT)
    return [ROOT / p.decode() for p in raw.split(b"\0") if p]


def strip_lean(text: str) -> str:
    """Strip nested comments and strings, preserving newlines and offsets."""
    out = list(text)
    i = 0
    depth = 0
    string = False
    escaped = False
    while i < len(text):
        if depth:
            if text.startswith("/-", i):
                out[i:i+2] = "  "
                depth += 1
                i += 2
            elif text.startswith("-/", i):
                out[i:i+2] = "  "
                depth -= 1
                i += 2
            else:
                if text[i] != "\n": out[i] = " "
                i += 1
            continue
        if string:
            if text[i] != "\n": out[i] = " "
            if escaped: escaped = False
            elif text[i] == "\\": escaped = True
            elif text[i] == '"': string = False
            i += 1
            continue
        if text.startswith("--", i):
            while i < len(text) and text[i] != "\n":
                out[i] = " "
                i += 1
            continue
        if text.startswith("/-", i):
            out[i:i+2] = "  "
            depth = 1
            i += 2
            continue
        if text[i] == '"':
            out[i] = " "
            string = True
        i += 1
    return "".join(out)


def category(rel: str) -> str:
    if rel.startswith("lean/ComparatorChallenges/"): return "challenge"
    if rel == "lean/OAI.lean" or rel.startswith("lean/OAI/"): return "solution"
    if rel.startswith("lean/docs/"): return "scope_doc"
    if rel.startswith("lean/patches/"): return "patch"
    return "other"


@dataclass(frozen=True)
class Finding:
    token: str
    path: str
    line: int
    category: str
    snippet: str


PATTERNS = {
    "sorry": re.compile(r"\bsorry\b"),
    "admit": re.compile(r"\badmit\b"),
    "axiom_decl": re.compile(r"^\s*axiom\s+", re.M),
    "opaque_decl": re.compile(r"^\s*opaque\s+", re.M),
    "unsafe_decl": re.compile(r"^\s*unsafe\s+(?:def|theorem|opaque|instance)\s+", re.M),
    "extern_decl": re.compile(r"^\s*(?:@\[extern[^\]]*\]\s*)?extern\s+", re.M),
    "implemented_by": re.compile(r"\bimplemented_by\b"),
    "native_decide": re.compile(r"\bnative_decide\b"),
    "by_exact_decide": re.compile(r"\bby\s+exact_decide\b"),
    "run_tac": re.compile(r"\brun_tac\b"),
    "classical_choose": re.compile(r"\bClassical\.choose\b"),
    "exists_choose": re.compile(r"\bExists\.choose\b"),
    "false_elim": re.compile(r"\bFalse\.elim\b"),
    "subsingleton_elim": re.compile(r"\bSubsingleton\.elim\b"),
    "local_instance": re.compile(r"^\s*local\s+instance\b", re.M),
    "local_instance_attribute": re.compile(r"attribute\s*\[\s*local\s+instance\s*\]"),
    "noncomputable": re.compile(r"^\s*noncomputable\s+(?:section|def|instance)\b", re.M),
    "autoimplicit_true": re.compile(r"set_option\s+autoImplicit\s+true\b"),
    "resource_option": re.compile(r"set_option\s+(?:maxRecDepth|maxHeartbeats|synthInstance\.maxHeartbeats)\b"),
    "broad_mathlib_import": re.compile(r"^\s*import\s+Mathlib\s*$", re.M),
}


def scan_sources(files: list[Path]) -> tuple[list[Finding], dict[str, str]]:
    findings: list[Finding] = []
    stripped: dict[str, str] = {}
    for path in files:
        rel = path.relative_to(ROOT).as_posix()
        original = path.read_text(encoding="utf-8")
        clean = strip_lean(original)
        stripped[rel] = clean
        lines = original.splitlines()
        for token, pattern in PATTERNS.items():
            for m in pattern.finditer(clean):
                line = clean.count("\n", 0, m.start()) + 1
                snippet = lines[line-1].strip()[:300] if line <= len(lines) else ""
                findings.append(Finding(token, rel, line, category(rel), snippet))
    return sorted(findings, key=lambda f: (f.path, f.line, f.token)), stripped


def module_name(path: Path) -> str | None:
    rel = path.relative_to(LEAN).with_suffix("").as_posix()
    if rel == "OAI": return "OAI"
    if rel.startswith("OAI/") or rel.startswith("ComparatorChallenges/"):
        return rel.replace("/", ".")
    return None


def imports(clean: str) -> list[str]:
    result: list[str] = []
    for m in re.finditer(r"^\s*import\s+([^\n]+)$", clean, re.M):
        result.extend(re.findall(r"[A-Za-z0-9_.'«»-]+", m.group(1)))
    return result


def import_audit(files: list[Path], stripped: dict[str, str]) -> dict[str, Any]:
    modules = {module_name(p): p.relative_to(ROOT).as_posix() for p in files if module_name(p)}
    edges: dict[str, list[str]] = {}
    challenge_imports = []
    broad = []
    unresolved = []
    for mod, rel in modules.items():
        deps = imports(stripped[rel])
        edges[mod] = deps
        if mod == "OAI" or mod.startswith("OAI."):
            for dep in deps:
                if dep.startswith("ComparatorChallenges"):
                    challenge_imports.append({"module": mod, "import": dep, "path": rel})
                if dep == "Mathlib": broad.append(rel)
                if dep.startswith("OAI") and dep not in modules:
                    unresolved.append({"module": mod, "import": dep, "path": rel})
    seen: set[str] = set()
    stack = ["OAI"] if "OAI" in modules else []
    while stack:
        cur = stack.pop()
        if cur in seen: continue
        seen.add(cur)
        stack.extend(d for d in edges.get(cur, []) if d in modules and d not in seen)
    oai = {m for m in modules if m == "OAI" or m.startswith("OAI.")}
    return {
        "known_modules": len(modules),
        "oai_modules": len(oai),
        "reachable_from_OAI": len(oai & seen),
        "unreachable_from_OAI": sorted(oai-seen),
        "oai_imports_challenges": challenge_imports,
        "broad_import_Mathlib": sorted(set(broad)),
        "unresolved_internal_imports": unresolved,
    }


def module_path(mod: str) -> Path:
    return LEAN / (mod.replace(".", "/") + ".lean")


def comparator_audit() -> dict[str, Any]:
    d = LEAN / "ComparatorChallenges"
    jsons = sorted(d.glob("*.json"))
    leans = sorted(d.glob("*.lean"))
    nanoda = collections.Counter()
    axiom_profiles = collections.Counter()
    invalid = []
    missing_challenge = []
    missing_solution = []
    no_same_stem = []
    unresolved_decls = []
    configs = []
    lean_stems = {p.stem for p in leans}
    for p in jsons:
        try:
            obj = json.loads(p.read_text())
        except Exception as exc:
            invalid.append({"path": p.relative_to(ROOT).as_posix(), "error": repr(exc)})
            continue
        challenge = obj.get("challenge_module")
        solution = obj.get("solution_module")
        theorems = obj.get("theorem_names", [])
        definitions = obj.get("definition_names", [])
        axioms = tuple(sorted(obj.get("permitted_axioms", [])))
        nanoda[str(obj.get("enable_nanoda", "missing")).lower()] += 1
        axiom_profiles[axioms] += 1
        if isinstance(challenge, str) and not module_path(challenge).exists(): missing_challenge.append(p.name)
        if isinstance(solution, str) and not module_path(solution).exists(): missing_solution.append(p.name)
        if p.stem not in lean_stems: no_same_stem.append(p.name)
        solution_text = ""
        if isinstance(solution, str) and module_path(solution).exists():
            solution_text = strip_lean(module_path(solution).read_text())
        for full in [*theorems, *definitions]:
            short = str(full).split(".")[-1]
            if solution_text and not re.search(rf"^\s*(?:theorem|lemma|def|abbrev|opaque|structure|class|inductive)\s+{re.escape(short)}\b", solution_text, re.M):
                unresolved_decls.append({"config": p.name, "solution": solution, "declaration": full})
        configs.append({
            "path": p.relative_to(ROOT).as_posix(), "challenge_module": challenge,
            "solution_module": solution, "theorem_names": theorems,
            "definition_names": definitions, "permitted_axioms": list(axioms),
            "enable_nanoda": obj.get("enable_nanoda", "missing"),
        })
    sorry_files, no_sorry_files = [], []
    for p in leans:
        (sorry_files if re.search(r"\bsorry\b", strip_lean(p.read_text())) else no_sorry_files).append(p.name)
    return {
        "config_count": len(jsons), "challenge_file_count": len(leans),
        "invalid_json": invalid, "nanoda_profile": dict(sorted(nanoda.items())),
        "permitted_axiom_profiles": [{"axioms": list(k), "count": v} for k,v in axiom_profiles.most_common()],
        "missing_challenge_modules": sorted(missing_challenge),
        "missing_solution_modules": sorted(missing_solution),
        "configs_without_same_stem_challenge": sorted(no_same_stem),
        "challenge_files_with_sorry": len(sorry_files),
        "challenge_files_without_sorry": no_sorry_files,
        "lexically_unresolved_named_declarations": unresolved_decls,
        "configs": configs,
    }


def lake_audit() -> dict[str, Any]:
    lakefile = LEAN / "lakefile.lean"
    text = lakefile.read_text()
    req_re = re.compile(r"^require\s+([^\s]+)\s+from\s+git\s*\n\s*\"([^\"]+)\"\s*@\s*\"([^\"]+)\"", re.M)
    reqs = [{"name":m.group(1),"url":m.group(2),"revision":m.group(3),"full_commit":bool(re.fullmatch(r"[0-9a-f]{40}",m.group(3)))} for m in req_re.finditer(text)]
    patches = []
    for p in sorted((LEAN/"patches").glob("*.patch")):
        patches.append({"path":p.relative_to(ROOT).as_posix(),"bytes":p.stat().st_size,"sha256":digest(p)})
    manifest_path = LEAN / "lake-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    packages = manifest.get("packages", []) if isinstance(manifest, dict) else []
    moving_manifest = []
    for pkg in packages if isinstance(packages, list) else []:
        if isinstance(pkg, dict) and pkg.get("type") == "git":
            rev = pkg.get("rev")
            if not isinstance(rev, str) or not re.fullmatch(r"[0-9a-f]{40}", rev): moving_manifest.append(pkg)
    signals = {s:text.count(s) for s in ["run_cmd","post_update","IO.Process","git","apply","clone","unsafe env.evalConstCheck",".lake/packages"] if s in text}
    return {
        "lakefile_sha256": digest(lakefile), "requirements": reqs,
        "moving_requirements": [r for r in reqs if not r["full_commit"]],
        "patch_count": len(patches), "patch_total_bytes": sum(p["bytes"] for p in patches),
        "patches": patches, "manifest_sha256": digest(manifest_path),
        "manifest_package_count": len(packages) if isinstance(packages, list) else 0,
        "moving_manifest_refs": moving_manifest, "configuration_execution_signals": signals,
    }


def file_modes() -> dict[str, list[str]]:
    symlinks, submodules = [], []
    for line in run("git","ls-files","-s").splitlines():
        m = re.match(r"^(\d+)\s+[0-9a-f]+\s+\d+\t(.+)$", line)
        if not m: continue
        if m.group(1) == "120000": symlinks.append(m.group(2))
        if m.group(1) == "160000": submodules.append(m.group(2))
    return {"symlinks": sorted(symlinks), "submodules": sorted(submodules)}


def markdown(report: dict[str, Any]) -> str:
    c = report["comparator"]; i = report["imports"]; l = report["lake"]
    lines = [
        "# Genesis rigor scan v2", "",
        f"- Commit: `{report['git']['commit']}`", f"- Tree: `{report['git']['tree']}`",
        f"- Scanner SHA-256: `{report['scanner']['sha256']}`",
        f"- Tracked files: **{report['git']['tracked_files']:,}**",
        f"- Lean files: **{report['source']['lean_files']:,}**", "",
        "## High-confidence policy violations", "",
    ]
    lines += [f"- **{x['code']}**: {x['detail']}" for x in report["policy_violations"]] or ["- None detected by this static scanner."]
    lines += ["", "## Review signals", ""]
    lines += [f"- **{x['code']}**: {x['detail']}" for x in report["review_signals"]] or ["- None."]
    lines += ["", "## Comparator", "",
        f"- Configurations: **{c['config_count']}**",
        f"- Challenge files: **{c['challenge_file_count']}**",
        f"- Challenge files with actual `sorry`: **{c['challenge_files_with_sorry']}**",
        f"- Nanoda profile: `{json.dumps(c['nanoda_profile'], sort_keys=True)}`",
        f"- Missing challenge modules: **{len(c['missing_challenge_modules'])}**",
        f"- Missing solution modules: **{len(c['missing_solution_modules'])}**",
        f"- Lexically unresolved configured declarations: **{len(c['lexically_unresolved_named_declarations'])}**", "",
        "## Import surface", "",
        f"- OAI modules: **{i['oai_modules']}**",
        f"- Reachable from `OAI.lean`: **{i['reachable_from_OAI']}**",
        f"- Unreachable from `OAI.lean`: **{len(i['unreachable_from_OAI'])}**",
        f"- OAI imports of Comparator challenges: **{len(i['oai_imports_challenges'])}**",
        f"- Exact `import Mathlib`: **{len(i['broad_import_Mathlib'])}**",
        f"- Unresolved internal imports: **{len(i['unresolved_internal_imports'])}**", "",
        "## Effective dependency source", "",
        f"- Parsed direct Git requirements: **{len(l['requirements'])}**",
        f"- Moving direct requirements: **{len(l['moving_requirements'])}**",
        f"- Compatibility patches: **{l['patch_count']}** ({l['patch_total_bytes']:,} bytes)",
        f"- Manifest packages: **{l['manifest_package_count']}**",
        f"- Moving manifest refs: **{len(l['moving_manifest_refs'])}**",
        f"- Configuration-time execution signals: `{json.dumps(l['configuration_execution_signals'], sort_keys=True)}`", "",
        "## Boundary", "",
        "This is a static source audit. It does not replace Lean elaboration, `#print axioms`, Comparator replay, independent-kernel replay, hostile mathematical review, or manuscript-to-statement comparison.", "",
    ]
    return "\n".join(lines)


def main() -> int:
    files = tracked()
    lean_files = sorted(p for p in files if p.suffix == ".lean")
    findings, stripped = scan_sources(lean_files)
    counts: dict[str, collections.Counter[str]] = collections.defaultdict(collections.Counter)
    for f in findings:
        counts[f.token][f.category] += 1; counts[f.token]["total"] += 1
    token_summary = {k:dict(v) for k,v in sorted(counts.items())}
    imp = import_audit(lean_files, stripped)
    comp = comparator_audit()
    lake = lake_audit()
    violations = []
    placeholders = [f for f in findings if f.category == "solution" and f.token in {"sorry","admit"}]
    if placeholders: violations.append({"code":"SOLUTION_PLACEHOLDER","detail":f"{len(placeholders)} actual `sorry`/`admit` tokens occur in the OAI solution tree."})
    if imp["oai_imports_challenges"]: violations.append({"code":"CHALLENGE_IMPORT","detail":f"{len(imp['oai_imports_challenges'])} OAI modules import ComparatorChallenges."})
    if comp["missing_challenge_modules"] or comp["missing_solution_modules"]: violations.append({"code":"BROKEN_COMPARATOR_MODULE","detail":"Comparator configuration references a missing module."})
    if lake["moving_requirements"] or lake["moving_manifest_refs"]: violations.append({"code":"MOVING_DEPENDENCY","detail":"A Git dependency is not frozen to a full commit."})
    review = []
    if lake["patch_count"]: review.append({"code":"PATCHED_DEPENDENCY_TREE","detail":f"{lake['patch_count']} patches ({lake['patch_total_bytes']:,} bytes) mutate dependency checkouts; effective identity is commit plus ordered patch set."})
    true_nanoda = int(comp["nanoda_profile"].get("true",0))
    review.append({"code":"INDEPENDENT_KERNEL_COVERAGE","detail":f"{true_nanoda} of {comp['config_count']} Comparator configurations declare `enable_nanoda: true`."})
    if imp["unreachable_from_OAI"]: review.append({"code":"ROOT_REACHABILITY","detail":f"{len(imp['unreachable_from_OAI'])} OAI modules are not lexically reachable from `OAI.lean`."})
    if imp["broad_import_Mathlib"]: review.append({"code":"BROAD_IMPORT","detail":f"{len(imp['broad_import_Mathlib'])} OAI files use exact `import Mathlib`."})
    rt = token_summary.get("run_tac",{}).get("solution",0)
    if rt: review.append({"code":"METAPROGRAMMED_PROOF","detail":f"{rt} `run_tac` occurrences require exact-toolchain replay."})
    li = token_summary.get("local_instance",{}).get("solution",0)+token_summary.get("local_instance_attribute",{}).get("solution",0)
    if li: review.append({"code":"ELABORATION_CONTEXT","detail":f"{li} local-instance declarations or attributes alter typeclass search."})
    if comp["lexically_unresolved_named_declarations"]: review.append({"code":"DECLARATION_RESOLUTION","detail":f"{len(comp['lexically_unresolved_named_declarations'])} configured declarations require Lean-environment resolution."})
    report = {
        "schema":"GenesisRigorScan/2",
        "git":{"commit":run("git","rev-parse","HEAD"),"tree":run("git","rev-parse","HEAD^{tree}"),"tracked_files":len(files),**file_modes()},
        "scanner":{"path":Path(__file__).relative_to(ROOT).as_posix(),"sha256":digest(Path(__file__)),"python":sys.version},
        "source":{"lean_files":len(lean_files),"token_summary":token_summary,"findings":[asdict(f) for f in findings]},
        "imports":imp,"comparator":comp,"lake":lake,
        "policy_violations":violations,"review_signals":review,
        "limitations":["Lexical scan is not Lean parsing.","No correctness, originality, priority, or authorship conclusion follows from this report."],
    }
    jp = OUT/"genesis-rigor-scan-v2.json"; mp = OUT/"genesis-rigor-scan-v2.md"
    jp.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
    mp.write_text(markdown(report))
    print(mp.read_text()); print(f"JSON_SHA256={digest(jp)}"); print(f"MARKDOWN_SHA256={digest(mp)}")
    return 1 if violations else 0

if __name__ == "__main__":
    raise SystemExit(main())
