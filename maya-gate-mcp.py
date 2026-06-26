#!/usr/bin/env python3
"""
Maya Gate MCP Server — Real-time validation hooks for AI tools.
Exposes all maya_gate_lib functions as MCP tools.
"""

import os
import sys
import json
import tempfile
from pathlib import Path
import sentry_sdk

sys.path.insert(0, str(Path.home() / "scripts"))
from maya_gate_lib import (
    validate_file, load_config, SKILLS_DIRS,
    validate_with_fixpackets, heal_file,
    check_ai_patterns, format_ai_findings,
    check_react, check_vue, check_django, check_laravel, check_next,
    check_express, check_spring, check_flutter,
    detect_version, generate_migration_plan, format_migration_plan,
    check_conventions, format_convention_findings,
    check_dlp, format_dlp_findings,
    compare_files, format_comparison,
    create_attestation, verify_attestation,
    calculate_score, score_to_grade,
    list_gates, approve_gate, skip_gate,
    query_stats,
)

from mcp.server.fastmcp import FastMCP

_sentry_dsn = os.environ.get("SENTRY_DSN", "")
if _sentry_dsn:
    sentry_sdk.init(
        dsn=_sentry_dsn, traces_sample_rate=0.1,
        environment="production", send_default_pii=False,
    )

_otel_endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "")
if _otel_endpoint:
    from otel import setup_otel
    setup_otel("maya-gate-mcp")

mcp = FastMCP("maya-gate", instructions="AI output validation gate — validate, heal, detect AI, audit frameworks, plan migrations, check conventions & DLP.")

def _file_not_found(p: str) -> str:
    return json.dumps({"error": f"File not found: {p}"})

def _exists(fp):
    return fp.exists()

@mcp.tool()
def validate_file_path(file_path: str, fixpackets: bool = False) -> str:
    """Validate a file for syntax and lint errors. Set fixpackets=true for structured fix guidance."""
    fp = Path(file_path).expanduser()
    if not _exists(fp):
        return _file_not_found(file_path)
    config = load_config()
    if fixpackets:
        return json.dumps(validate_with_fixpackets(str(fp), config), indent=2)
    ok, results = validate_file(str(fp), config)
    return json.dumps({"pass": ok, "file": fp.name, "checks": {k: {"pass": v["pass"], "detail": v["detail"][:200]} for k, v in results.items()}}, indent=2)

@mcp.tool()
def validate_code(code: str, language: str = "python") -> str:
    """Validate inline code snippet. language: python, javascript, typescript, rust."""
    ext_map = {"python": ".py", "javascript": ".js", "typescript": ".ts", "rust": ".rs"}
    ext = ext_map.get(language, ".py")
    with tempfile.NamedTemporaryFile(mode="w", suffix=ext, delete=False) as f:
        f.write(code); tmp = f.name
    config = load_config()
    ok, results = validate_file(tmp, config)
    Path(tmp).unlink(missing_ok=True)
    return json.dumps({"pass": ok, "language": language, "checks": {k: {"pass": v["pass"], "detail": v["detail"][:200]} for k, v in results.items()}}, indent=2)

@mcp.tool()
def gate_status(file_path: str = "") -> str:
    """Return current gate health, config, score, and skill integrity."""
    config = load_config()
    skills_verified = skills_total = 0
    for sd in SKILLS_DIRS:
        if not sd.exists():
            continue
        for sk in sd.iterdir():
            if sk.is_dir():
                skills_total += 1
                if (sk / "INTEGRITY.json").exists():
                    skills_verified += 1
    score_data = {}
    if file_path and Path(file_path).expanduser().exists():
        s = calculate_score(str(Path(file_path).expanduser()))
        g, lbl = score_to_grade(s)
        score_data = {"score": s, "grade": g, "label": lbl}
    return json.dumps({"level": config["level"], "checks_active": [k for k, v in config["checks"].items() if v], "skills_total": skills_total, "skills_verified": skills_verified, "version": "2.0", "score": score_data}, indent=2)

@mcp.tool()
def attest(file_path: str) -> str:
    """Generate a signed Ed25519 attestation. Tamper-evident."""
    fp = Path(file_path).expanduser()
    if not _exists(fp):
        return _file_not_found(file_path)
    cfg = load_config()
    ok, results = validate_file(str(fp), cfg)
    att = create_attestation(str(fp), {"pass": ok, "checks": results}, cfg["level"])
    return json.dumps(att, indent=2)

@mcp.tool()
def verify_att(attestation_id_or_path: str) -> str:
    """Verify a signed attestation by ID (att_xxx) or file path."""
    att_dir = Path.home() / ".maya-gate/attestations"
    att_file = att_dir / f"{attestation_id_or_path}.json" if attestation_id_or_path.startswith("att_") else Path(attestation_id_or_path)
    if not _exists(att_file):
        return json.dumps({"error": f"Attestation not found: {attestation_id_or_path}"})
    valid, msg = verify_attestation(str(att_file))
    return json.dumps({"valid": valid, "message": msg, "file": str(att_file)}, indent=2)

@mcp.tool()
def heal_file_tool(file_path: str, dry_run: bool = True) -> str:
    """Auto-fix syntax and lint issues. dry_run=True previews without applying."""
    fp = Path(file_path).expanduser()
    if not _exists(fp):
        return _file_not_found(file_path)
    fixed, errors = heal_file(str(fp))
    return json.dumps({"file": str(fp), "fixed": fixed, "errors": errors, "dry_run": dry_run}, indent=2)

@mcp.tool()
def check_ai_patterns_tool(file_path: str, deep: bool = False) -> str:
    """Detect AI-generated code patterns and style markers. deep=True for slower thorough analysis."""
    fp = Path(file_path).expanduser()
    if not _exists(fp):
        return _file_not_found(file_path)
    findings = check_ai_patterns(str(fp), deep=deep)
    return json.dumps({"file": str(fp), "deep": deep, "total_findings": len(findings), "findings": format_ai_findings(findings)}, indent=2)

@mcp.tool()
def check_framework_tool(file_path: str) -> str:
    """Check file against framework best practices: React, Vue, Django, Laravel, Next.js, Express, Spring, Flutter."""
    fp = Path(file_path).expanduser()
    if not _exists(fp):
        return _file_not_found(file_path)
    fp_str = str(fp)
    results = []
    for checker, name in [
        (check_react, "react"), (check_vue, "vue"), (check_django, "django"),
        (check_laravel, "laravel"), (check_next, "next.js"),
        (check_express, "express"), (check_spring, "spring"), (check_flutter, "flutter"),
    ]:
        try:
            ok, msg = checker(fp_str)
            if ok:
                results.append({"framework": name, "pass": ok, "message": msg})
        except Exception:
            pass
    if not results:
        return json.dumps({"file": str(fp), "frameworks_tested": [], "note": "No matching framework detected."}, indent=2)
    return json.dumps({"file": str(fp), "frameworks_tested": results}, indent=2)

@mcp.tool()
def detect_framework_version_tool(file_path: str) -> str:
    """Detect which framework(s) a file belongs to and their version."""
    fp = Path(file_path).expanduser()
    if not _exists(fp):
        return _file_not_found(file_path)
    results = []
    for framework in ["react", "vue", "django", "laravel", "next.js", "express", "spring", "flutter"]:
        try:
            v = detect_version(framework, str(fp))
            if v:
                results.append({"framework": framework, "version": v})
        except Exception:
            pass
    if not results:
        return json.dumps({"file": str(fp), "note": "Could not detect any framework version."}, indent=2)
    return json.dumps({"file": str(fp), "frameworks": results}, indent=2)

@mcp.tool()
def plan_migration_tool(framework: str, from_version: str, to_version: str) -> str:
    """Generate a step-by-step migration plan. Examples: react 17→18, django 3→5, laravel 8→10, next.js 12→14."""
    try:
        plan = generate_migration_plan(framework, from_version, to_version)
        formatted = format_migration_plan(plan, framework)
        return json.dumps({"framework": framework, "from": from_version, "to": to_version, "plan": formatted}, indent=2)
    except Exception as e:
        return json.dumps({"error": f"Migration plan failed: {e}"}, indent=2)

@mcp.tool()
def check_conventions_tool(file_path: str, framework: str = "python") -> str:
    """Check file against codebase conventions. framework: python, javascript, typescript, react, vue."""
    fp = Path(file_path).expanduser()
    if not _exists(fp):
        return _file_not_found(file_path)
    findings = check_conventions(str(fp), framework=framework)
    return json.dumps({"file": str(fp), "framework": framework, "total": len(findings), "findings": format_convention_findings(findings, framework=framework)}, indent=2)

@mcp.tool()
def check_dlp_tool(file_path: str) -> str:
    """Check file for data leakage: secrets, API keys, tokens, PII."""
    fp = Path(file_path).expanduser()
    if not _exists(fp):
        return _file_not_found(file_path)
    findings = check_dlp(str(fp))
    return json.dumps({"file": str(fp), "total": len(findings), "findings": format_dlp_findings(findings)}, indent=2)

@mcp.tool()
def compare_files_tool(old_path: str, new_path: str) -> str:
    """Compare two files and report differences for audit/review."""
    old_fp = Path(old_path).expanduser()
    new_fp = Path(new_path).expanduser()
    if not _exists(old_fp):
        return _file_not_found(old_path)
    if not _exists(new_fp):
        return _file_not_found(new_path)
    result = compare_files(str(old_fp), str(new_fp))
    return json.dumps({"old": str(old_fp), "new": str(new_fp), "result": format_comparison(result)}, indent=2)

@mcp.tool()
def gate_stats_tool(since: str = "7d", by_language: bool = False, by_framework: bool = False) -> str:
    """Query gate validation statistics. since: 24h, 7d (default), 30d. Toggle by_language/by_framework."""
    stats = query_stats(since=since, by_language=by_language, by_framework=by_framework)
    return json.dumps(stats, indent=2)

@mcp.tool()
def approve_gate_tool(gate_id: str, reason: str = "") -> str:
    """Approve a pending gate. Human-in-the-loop."""
    ok, msg = approve_gate(gate_id, reason)
    return json.dumps({"ok": ok, "message": msg}, indent=2)

@mcp.tool()
def skip_gate_tool(gate_id: str, reason: str = "") -> str:
    """Skip/reject a pending gate with a reason."""
    ok, msg = skip_gate(gate_id, reason)
    return json.dumps({"ok": ok, "message": msg}, indent=2)

@mcp.tool()
def list_gates_tool() -> str:
    """List all pending approval gates."""
    gates = [g for g in list_gates() if g.status == "pending"]
    return json.dumps([g.to_dict() for g in gates], indent=2)

def main():
    print("🚪 Maya Gate MCP Server starting (stdio)...", file=sys.stderr)
    mcp.run()

if __name__ == "__main__":
    main()
