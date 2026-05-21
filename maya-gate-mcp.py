#!/usr/bin/env python3
"""
Maya Gate MCP Server — Real-time validation hooks for AI tools.
Exposes validate, status, and attest tools via Model Context Protocol.
"""

import sys
import json
import tempfile
from pathlib import Path

# Add scripts dir to path for maya-gate imports
sys.path.insert(0, str(Path.home() / "scripts"))
from maya_gate_lib import validate_file, load_config, SKILLS_DIRS, validate_with_fixpackets, create_attestation, verify_attestation, calculate_score, score_to_grade, list_gates, approve_gate

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("maya-gate", instructions="AI output validation gate — validate code, check status, generate attestations.")


@mcp.tool()
def validate_file_path(file_path: str, fixpackets: bool = False) -> str:
    """Validate a file for syntax and lint errors. Set fixpackets=true for structured fix guidance."""
    fp = Path(file_path).expanduser()
    if not fp.exists():
        return json.dumps({"error": f"File not found: {file_path}"})
    config = load_config()
    
    if fixpackets:
        pkt = validate_with_fixpackets(str(fp), config)
        return json.dumps(pkt, indent=2)
    
    ok, results = validate_file(str(fp), config)
    return json.dumps({
        "pass": ok,
        "file": fp.name,
        "checks": {k: {"pass": v["pass"], "detail": v["detail"][:200]} for k, v in results.items()}
    }, indent=2)


@mcp.tool()
def validate_code(code: str, language: str = "python") -> str:
    """Validate inline code snippet. Specify language: python, javascript, typescript, rust."""
    ext_map = {"python": ".py", "javascript": ".js", "typescript": ".ts", "rust": ".rs"}
    ext = ext_map.get(language, ".py")
    with tempfile.NamedTemporaryFile(mode="w", suffix=ext, delete=False) as f:
        f.write(code)
        tmp = f.name
    config = load_config()
    ok, results = validate_file(tmp, config)
    Path(tmp).unlink(missing_ok=True)
    return json.dumps({
        "pass": ok,
        "language": language,
        "checks": {k: {"pass": v["pass"], "detail": v["detail"][:200]} for k, v in results.items()}
    }, indent=2)


@mcp.tool()
def gate_status(file_path: str = "") -> str:
    """Return current gate health, config, score, and skill integrity status."""
    config = load_config()
    skills_verified = 0
    skills_total = 0
    for sd in SKILLS_DIRS:
        if not sd.exists(): continue
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
    
    return json.dumps({
        "level": config["level"],
        "checks_active": [k for k, v in config["checks"].items() if v],
        "skills_total": skills_total,
        "skills_verified": skills_verified,
        "version": "2.0",
        "score": score_data
    }, indent=2)


@mcp.tool()
def attest(file_path: str) -> str:
    """Generate a signed Ed25519 attestation for a validated file. Tamper-evident."""
    fp = Path(file_path).expanduser()
    if not fp.exists():
        return json.dumps({"error": f"File not found: {file_path}"})
    cfg = load_config()
    ok, results = validate_file(str(fp), cfg)
    att = create_attestation(str(fp), {"pass": ok, "checks": results}, cfg["level"])
    return json.dumps(att, indent=2)


@mcp.tool()
def verify_att(attestation_id_or_path: str) -> str:
    """Verify a signed attestation by ID (att_xxx) or file path."""
    from pathlib import Path
    att_dir = Path.home() / ".maya-gate/attestations"
    if attestation_id_or_path.startswith("att_"):
        att_file = att_dir / f"{attestation_id_or_path}.json"
    else:
        att_file = Path(attestation_id_or_path)
    if not att_file.exists():
        return json.dumps({"error": f"Attestation not found: {attestation_id_or_path}"})
    valid, msg = verify_attestation(str(att_file))
    return json.dumps({"valid": valid, "message": msg, "file": str(att_file)}, indent=2)


@mcp.tool()
def approve_gate_tool(gate_id: str, reason: str = "") -> str:
    """Approve a pending approval gate. Human-in-the-loop verification."""
    ok, msg = approve_gate(gate_id, reason)
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
