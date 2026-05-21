"""
Maya Gate Library — shared functions for CLI and MCP server.
Import: from maya_gate_lib import validate_file, load_config, ...
"""

import subprocess
import sys
import os
import json
import hashlib
import re
import datetime
import uuid
import base64
from pathlib import Path

# Initialize tentacles
from maya_gate_tentacle import init as _tentacle_init, dispatch_syntax
_tentacle_registry = _tentacle_init()

# ── Feature Tiers ───────────────────────────────────────────────
CONFIG_DIR = Path.home() / ".config/maya-gate"

# MAYA_GATE_ENTERPRISE=1 (env) or config.json `enterprise: true`
# unlocks Ed25519 attestations, tamper detection, secrets management.
ENTERPRISE = os.environ.get("MAYA_GATE_ENTERPRISE", "") == "1"
if not ENTERPRISE:
    try:
        cfg = json.loads((CONFIG_DIR / "config.json").read_text())
        ENTERPRISE = cfg.get("enterprise", False)
    except Exception:
        pass

# Ed25519 for attestations (enterprise only)
if ENTERPRISE:
    from cryptography.hazmat.primitives.asymmetric import ed25519
    from cryptography.hazmat.primitives import serialization
    from cryptography.exceptions import InvalidSignature

CONFIG_DIR = Path.home() / ".config/maya-gate"
CONFIG_FILE = CONFIG_DIR / "config.json"
SKILLS_DIRS = [Path.home() / "plugins/maya-skills/skills", Path.home() / ".agents/skills"]

DEFAULT_CONFIG = {
    "level": "l2", "max_iterations": 3,
    "checks": {"syntax": True, "ruff": True, "snip": False, "compile": True},
    "watch_extensions": [".py", ".js", ".ts", ".rs", ".go", ".java", ".cs", ".c", ".cpp", ".h", ".hpp", ".php", ".rb"],
    "quiet": False
}

LEVELS = {
    "l1": {"syntax": True, "ruff": False, "snip": False, "compile": True},
    "l2": {"syntax": True, "ruff": True, "snip": False, "compile": True},
    "l3": {"syntax": True, "ruff": True, "snip": True, "compile": True},
}


def load_config():
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE) as f:
            return {**DEFAULT_CONFIG, **json.load(f)}
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(DEFAULT_CONFIG, indent=2) + "\n")
    return DEFAULT_CONFIG


def check_syntax(fp):
    import shutil
    ext = Path(fp).suffix
    if ext == ".py":
        r = subprocess.run([sys.executable, "-c", f"compile(open('{fp}').read(),'{fp}','exec')"], capture_output=True, text=True)
        return r.returncode == 0, r.stderr or r.stdout
    if ext in (".js", ".ts"):
        r = subprocess.run(["node", "--check", fp], capture_output=True, text=True)
        return r.returncode == 0, r.stderr or r.stdout
    if ext == ".rs":
        out = "/tmp/rust_check_out"
        r = subprocess.run(["rustc", "--edition", "2021", fp, "-o", out], capture_output=True, text=True, timeout=15)
        Path(out).unlink(missing_ok=True)
        return r.returncode == 0, r.stderr or r.stdout
    if ext == ".go" and shutil.which("go"):
        r = subprocess.run(["go", "vet", fp], capture_output=True, text=True, timeout=15)
        return r.returncode == 0, r.stderr or r.stdout
    if ext == ".java" and shutil.which("javac"):
        r = subprocess.run(["javac", "-Xlint:all", "-proc:none", fp], capture_output=True, text=True, timeout=15)
        Path(fp).with_suffix(".class").unlink(missing_ok=True)
        return r.returncode == 0, r.stderr or r.stdout
    if ext == ".cs" and shutil.which("dotnet"):
        src_dir = Path(fp).parent
        proj_files = list(src_dir.glob("*.csproj"))
        
        if not proj_files:
            tmp_proj_dir = Path("/tmp/maya-gate-cs")
            tmp_proj_dir.mkdir(parents=True, exist_ok=True)
            proj_path = tmp_proj_dir / "check.csproj"
            
            if not proj_path.exists():
                proj_path.write_text("""<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup><OutputType>Exe</OutputType><TargetFramework>net8.0</TargetFramework></PropertyGroup>
</Project>""")
            
            import shutil as _shutil
            _shutil.copy2(fp, tmp_proj_dir / "Program.cs")
            
            r = subprocess.run(
                ["dotnet", "build", str(tmp_proj_dir)],
                capture_output=True, text=True, timeout=60,
                env={**os.environ, "DOTNET_NOLOGO": "1", "DOTNET_CLI_TELEMETRY_OPTOUT": "1"}
            )
            (tmp_proj_dir / "Program.cs").unlink(missing_ok=True)
            return r.returncode == 0, r.stderr or r.stdout
        else:
            r = subprocess.run(["dotnet", "build", "--no-restore", str(src_dir)], capture_output=True, text=True, timeout=30)
            return r.returncode == 0, r.stderr or r.stdout
    if ext in (".c", ".cpp", ".h", ".hpp") and shutil.which("gcc"):
        lang = "c++" if ext in (".cpp", ".hpp") else "c"
        out = Path("/dev/null")
        r = subprocess.run(["gcc", "-x", lang, "-fsyntax-only", "-Wall", "-Wextra", fp, "-o", str(out)], capture_output=True, text=True, timeout=15)
        return r.returncode == 0, r.stderr or r.stdout
    if ext == ".php" and shutil.which("php"):
        r = subprocess.run(["php", "-l", fp], capture_output=True, text=True)
        return r.returncode == 0, r.stderr or r.stdout
    if ext == ".rb" and shutil.which("ruby"):
        r = subprocess.run(["ruby", "-c", fp], capture_output=True, text=True)
        return r.returncode == 0, r.stderr or r.stdout
    return True, f"no syntax checker for {ext} files"


def check_ruff(fp):
    import shutil
    if not shutil.which("ruff"): return True, ""
    r = subprocess.run(["ruff", "check", str(fp), "--quiet"], capture_output=True, text=True)
    return r.returncode == 0, r.stdout or r.stderr


def check_snip(fp):
    import shutil
    if not shutil.which("snip"): return True, ""
    r = subprocess.run(["snip", "run", "--", "cat", str(fp)], capture_output=True, text=True, timeout=10)
    return r.returncode == 0, r.stdout or r.stderr


def validate_file(fp, cfg):
    results = {}
    ok = True
    if cfg["checks"]["syntax"]:
        p, e = check_syntax(fp); results["syntax"] = {"pass": p, "detail": e.strip()}; ok &= p
    if cfg["checks"]["ruff"]:
        p, e = check_ruff(fp); results["ruff"] = {"pass": p, "detail": e.strip()}; ok &= p
    if cfg["checks"]["snip"]:
        p, e = check_snip(fp); results["snip"] = {"pass": p, "detail": e.strip()}; ok &= p
    # Tentacle syntax checks
    try:
        for name, t_ok, t_msg in dispatch_syntax(fp):
            if not t_ok:
                results[f"tentacle/{name}"] = {"pass": False, "detail": t_msg}
                ok = False
    except Exception:
        pass
    return ok, results


def hash_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


# ── Phase 3: Fix Packet Protocol ───────────────────────────────

FIX_PACKET_VERSION = 1


def _parse_syntax_error(err_text, file_path):
    """Parse Python syntax error and extract line + suggested fix."""
    findings = []
    for line in err_text.split("\n"):
        m = re.match(r'\s*File "(.*?)", line (\d+)', line)
        if m:
            line_no = int(m.group(2))
            try:
                source = Path(file_path).read_text().split("\n")
                bad_line = source[line_no - 1] if line_no <= len(source) else ""
            except Exception:
                bad_line = ""
            findings.append({"line": line_no, "bad_line": bad_line})
    
    # Get the error message
    msg_match = re.search(r"(SyntaxError|IndentationError|NameError|TypeError): (.+)", err_text)
    error_msg = msg_match.group(2) if msg_match else err_text[:200]

    fixes = []
    for f in findings:
        fix = bad_line = f["bad_line"]
        # Common fix patterns
        if bad_line.rstrip().endswith(":") and "def " in bad_line or "class " in bad_line or "if " in bad_line or "elif " in bad_line or "else" in bad_line or "for " in bad_line or "while " in bad_line:
            fix = bad_line  # already correct
        elif bad_line.rstrip().endswith(("(", "[", "{", ",")):
            fix = bad_line.rstrip() + ")"
        elif "unexpected indent" in err_text.lower() and bad_line.strip():
            fix = "    " + bad_line.lstrip()
        elif "expected ':'" in err_text.lower():
            fix = bad_line.rstrip() + ":"
        else:
            fix = f"# FIXME: {error_msg}"

        fixes.append({
            "line": f["line"],
            "original": bad_line,
            "suggested": fix,
            "confidence": "high" if fix != f"# FIXME: {error_msg}" else "low"
        })

    return {
        "id": "SYNTAX-001",
        "check": "syntax",
        "severity": "error",
        "message": error_msg.strip(),
        "fixes": fixes,
        "provenance": "compile()"
    }


def _parse_ruff_errors(err_text, file_path):
    """Parse ruff JSON output into fix findings."""
    import shutil
    if not shutil.which("ruff"):
        return []
    
    # Get JSON output from ruff
    r = subprocess.run(["ruff", "check", str(file_path), "--output-format", "json", "--quiet"],
                       capture_output=True, text=True, timeout=10)
    findings = []
    try:
        issues = json.loads(r.stdout) if r.stdout.strip() else []
    except Exception:
        return []

    for issue in issues:
        fix_text = ""
        if issue.get("fix"):
            fix_text = issue["fix"].get("applicability", "sometimes")
        
        fixes = [{
            "line": issue.get("location", {}).get("row", 0),
            "original": "",
            "suggested": f"ruff auto-fix available ({issue.get('code', '')})" if fix_text else "manual review needed",
            "confidence": "high" if fix_text else "medium"
        }]

        findings.append({
            "id": issue.get("code", "RUFF-000"),
            "check": "ruff",
            "severity": issue.get("cell", "warning") if not issue.get("fix") else "warning",
            "message": issue.get("message", ""),
            "fixes": fixes,
            "provenance": "ruff"
        })
    return findings


def _make_fix_packet(fp, checks_passed, syntax_finding, ruff_findings):
    """Build a Fix Packet JSON structure."""
    file_checks = []
    if syntax_finding:
        file_checks.append(syntax_finding)
    file_checks.extend(ruff_findings)

    content = Path(fp).read_bytes() if Path(fp).exists() else b""

    return {
        "version": FIX_PACKET_VERSION,
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "pass": checks_passed,
        "files": [{
            "path": str(fp),
            "size": len(content),
            "checks": file_checks
        }],
        "hash": hashlib.sha256(content).hexdigest()
    }


def validate_with_fixpackets(fp, cfg):
    """Validate a file and return Fix Packet JSON."""
    ok, results = validate_file(fp, cfg)
    syntax_finding = None
    ruff_findings = []

    if cfg["checks"]["syntax"] and not results.get("syntax", {}).get("pass", True):
        syntax_finding = _parse_syntax_error(
            results["syntax"].get("detail", ""), fp
        )

    if cfg["checks"]["ruff"] and not results.get("ruff", {}).get("pass", True):
        ruff_findings = _parse_ruff_errors(
            results["ruff"].get("detail", ""), fp
        )

    return _make_fix_packet(fp, ok, syntax_finding, ruff_findings)


def heal_file(fp):
    """Apply auto-fixes to a file. Returns (fixed_count, errors)."""
    import shutil
    fixed = 0
    errors = []

    if not Path(fp).exists():
        return 0, ["File not found"]

    ext = Path(fp).suffix

    # ruff auto-fix
    if ext == ".py" and shutil.which("ruff"):
        r = subprocess.run(
            ["ruff", "check", "--fix", str(fp), "--quiet"],
            capture_output=True, text=True, timeout=10
        )
        # Count fixes applied
        stderr = r.stderr or ""
        for line in stderr.split("\n"):
            m = re.search(r"(\d+) fixable", line)
            if m:
                fixed += int(m.group(1))

    if fixed == 0 and not errors:
        return 0, ["No auto-fixable issues found"]

    return fixed, errors


def format_fix_packet(packet):
    """Pretty-print a Fix Packet for terminal display."""
    passed = packet["pass"]
    status = "✅" if passed else "❌"
    print(f"\n  {status} Fix Packet v{packet['version']}")
    print(f"     Hash: {packet['hash'][:16]}...")
    
    for f in packet["files"]:
        print(f"     File: {f['path']}")
        for c in f["checks"]:
            icon = "✅" if c.get("severity") == "warning" else "❌"
            print(f"       {icon} [{c['id']}] {c['message'][:80]}")
            for fx in c["fixes"]:
                if fx["suggested"] and not fx["suggested"].startswith("# FIXME"):
                    print(f"         → Line {fx['line']}: {fx['suggested'][:80]}")
    
    return packet


# ── Phase 4: Signed Attestations (enterprise only) ──────────────

if not ENTERPRISE:
    def create_attestation(fp, results, level="l2"):
        print("🔒 Enterprise feature — set MAYA_GATE_ENTERPRISE=1")
        sys.exit(1)
    def verify_attestation(attest_path):
        print("🔒 Enterprise feature — set MAYA_GATE_ENTERPRISE=1")
        sys.exit(1)
    def list_attestations(limit=10):
        print("🔒 Enterprise feature — set MAYA_GATE_ENTERPRISE=1")
        sys.exit(1)
    def _ensure_identity():
        print("🔒 Enterprise feature — set MAYA_GATE_ENTERPRISE=1")
        sys.exit(1)
else:
    ATTEST_DIR = Path.home() / ".maya-gate/attestations"
    IDENTITY_FILE = CONFIG_DIR / "identity.key"
    IDENTITY_PUB_FILE = CONFIG_DIR / "identity.pub"
    _identity_private = None
    _identity_public = None


    def _ensure_identity():
        """Load or generate Ed25519 identity."""
        global _identity_private, _identity_public
        if _identity_private is not None:
            return _identity_private, _identity_public

        CONFIG_DIR.mkdir(parents=True, exist_ok=True)

        if IDENTITY_FILE.exists():
            _identity_private = ed25519.Ed25519PrivateKey.from_private_bytes(
                IDENTITY_FILE.read_bytes()
            )
            _identity_public = _identity_private.public_key()
        else:
            _identity_private = ed25519.Ed25519PrivateKey.generate()
            _identity_public = _identity_private.public_key()
            IDENTITY_FILE.write_bytes(
                _identity_private.private_bytes(
                    encoding=serialization.Encoding.Raw,
                    format=serialization.PrivateFormat.Raw,
                    encryption_algorithm=serialization.NoEncryption()
                )
            )
            IDENTITY_PUB_FILE.write_bytes(
                _identity_public.public_bytes(
                    encoding=serialization.Encoding.Raw,
                    format=serialization.PublicFormat.Raw
                )
            )
            os.chmod(IDENTITY_FILE, 0o600)
            print(f"  🔑 Ed25519 identity generated: {IDENTITY_FILE}")

        return _identity_private, _identity_public


    def _sign(data_bytes):
        """Sign bytes with the identity key."""
        priv, _ = _ensure_identity()
        return priv.sign(data_bytes)


    def _verify(data_bytes, signature):
        """Verify bytes against the identity's signature."""
        _, pub = _ensure_identity()
        try:
            pub.verify(signature, data_bytes)
            return True
        except InvalidSignature:
            return False


    def _get_git_context():
        """Get git commit + diff hash for attestation context."""
        ctx = {"commit": "", "diff_hash": "", "branch": ""}
        try:
            r = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5)
            if r.returncode == 0:
                ctx["commit"] = r.stdout.strip()
            r = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True, text=True, timeout=5)
            if r.returncode == 0:
                ctx["branch"] = r.stdout.strip()
            r = subprocess.run(["git", "diff", "HEAD", "--stat"], capture_output=True, text=True, timeout=5)
            if r.returncode == 0:
                ctx["diff_hash"] = hashlib.sha256(r.stdout.encode()).hexdigest()
        except Exception:
            pass
        return ctx


    def create_attestation(fp, results, level="l2"):
        """Create a signed attestation for a validation result.
        If fp is a directory, creates a manifest of all files within.
        """
        ATTEST_DIR.mkdir(parents=True, exist_ok=True)
        
        attest_id = f"att_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        target = Path(fp)
        
        if target.is_dir():
            files = sorted([f for f in target.rglob("*") if f.is_file() and '.git' not in str(f)])
            manifest = [(str(f.relative_to(target)), f.stat().st_size, hashlib.sha256(f.read_bytes()).hexdigest()) for f in files[:100]]
            content = json.dumps(manifest, indent=2).encode()
            file_info = {"path": str(fp), "type": "directory", "files": len(files)}
        elif target.exists():
            content = target.read_bytes()
            file_info = {"path": str(fp), "size": len(content), "hash": hashlib.sha256(content).hexdigest()}
        else:
            content = b""
            file_info = {"path": str(fp), "exists": False}

        attestation = {
            "version": 1,
            "id": attest_id,
            "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "tool": "maya-gate",
            "level": level,
            "results": {
                "pass": results.get("pass", False),
                "checks": {k: v["pass"] for k, v in results.get("checks", {}).items()}
            },
            "git": _get_git_context(),
            "file": file_info,
            "signer": os.environ.get("USER", "unknown")
        }

        # Sign
        data_bytes = json.dumps(attestation, sort_keys=True).encode()
        sig = _sign(data_bytes)
        attestation["signature"] = "ed25519:" + base64.b64encode(sig).decode()

        # Save
        att_path = ATTEST_DIR / f"{attest_id}.json"
        att_path.write_text(json.dumps(attestation, indent=2) + "\n")

        return attestation


    def verify_attestation(attest_path):
        """Load and verify an attestation file."""
        att = json.loads(Path(attest_path).read_text())
        signature = att.pop("signature", "")
        if not signature:
            return False, "No signature found"
        
        sig_bytes = base64.b64decode(signature.replace("ed25519:", ""))
        data_bytes = json.dumps(att, sort_keys=True).encode()
        
        valid = _verify(data_bytes, sig_bytes)
        return valid, "Signature valid" if valid else "Signature INVALID — tampered"


    def list_attestations(limit=10):
        """List recent attestations."""
        ATTEST_DIR.mkdir(parents=True, exist_ok=True)
        files = sorted(ATTEST_DIR.glob("att_*.json"), reverse=True)[:limit]
        atts = []
        for f in files:
            try:
                att = json.loads(f.read_text())
                atts.append({
                    "id": att["id"],
                    "created_at": att["created_at"][:19],
                    "pass": att["results"]["pass"],
                    "file": att["file"]["path"],
                    "signer": att["signer"]
                })
            except Exception:
                pass
        return atts


# ── Phase 5: AI Behavior Pattern Detection ─────────────────────

AI_PATTERNS = [
    {
        "id": "AI-HEDGE-001",
        "name": "Hedging comments",
        "severity": "warning",
        "patterns": [
            r"#\s*(we should|we might|we could|maybe we|perhaps we|it might be better)",
            r"#\s*(this might|this could|this should|this would|this may)",
            r"#\s*(i think|i believe|i suspect|in my opinion)",
            r"//\s*(we should|we might|we could|maybe we|perhaps we)",
            r"//\s*(this might|this could|this should|i think|todo: consider)",
        ],
        "message": "Hedging language — AI is uncertain about this code"
    },
    {
        "id": "AI-APOL-001",
        "name": "Apologetic comments",
        "severity": "warning",
        "patterns": [
            r"#\s*(sorry|apologies|apologize|pardon)",
            r"#\s*(this is a quick|this is a rough|this is a temporary|this is a hack)",
            r"#\s*(i know this|this is not ideal|this isn't perfect|this could be better)",
            r"#\s*(forgive|bear with|workaround|kludge|hacky)",
            r"//\s*(sorry|this is a quick|this is a hack|workaround)",
        ],
        "message": "Apologetic language — AI is unsure about quality"
    },
    {
        "id": "AI-TODO-001",
        "name": "Placeholder comments",
        "severity": "warning",
        "patterns": [
            r"#\s*(TODO|FIXME|XXX|HACK|BUG|OPTIMIZE|REVIEW|TEMP|WORKAROUND)",
            r"#\s*(implement|add|finish|complete|handle this|need to)",
            r"//\s*(TODO|FIXME|XXX|HACK|BUG|OPTIMIZE|TEMP)",
            r"/\*.*?(TODO|FIXME|XXX).*?\*/",
        ],
        "message": "Placeholder left by AI — needs human review"
    },
    {
        "id": "AI-VERB-001",
        "name": "Overly verbose comments",
        "severity": "info",
        "patterns": [
            r"#\s*(this function|this method|this class|this code|this block)\s",
            r"#\s*(the following|below|above|as mentioned|as shown)",
            r"#\s*(in other words|that is|i\.e\.|e\.g\.|namely)",
            r"#\s*(firstly|secondly|lastly|finally|additionally|furthermore)",
            r"//\s*(this function|this method|this class|this code)\s",
        ],
        "message": "Overly explanatory — AI is compensating for uncertainty"
    },
    {
        "id": "AI-DEAD-001",
        "name": "Dead / unreachable code",
        "severity": "warning",
        "patterns": [
            r"#\s*(this line is never reached|unreachable|dead code)",
            r"#\s*(commented out|disabled|turned off|not used|unused)",
            r"//\s*(commented out|disabled|never reached|not used)",
            r"if\s+False\s*:",
            r"if\s+0\s*:",
            r"while\s+False\s*:",
        ],
        "message": "Dead code — AI left unused or unreachable blocks"
    },
    {
        "id": "AI-HALL-001",
        "name": "Hallucinated imports",
        "severity": "error",
        "patterns": [
            r"^import\s+(\w+)",
            r"^from\s+(\w+(?:\.\w+)*)\s+import",
        ],
        "message": "Potential hallucinated import — verify package exists"
    },
]

# Cache for import validation
_HALLUCINATION_CACHE = {}

# Known stdlib modules — never flag these
_STDLIB_MODULES = {
    "os", "sys", "re", "json", "math", "time", "datetime", "pathlib",
    "collections", "itertools", "functools", "typing", "argparse",
    "subprocess", "shutil", "hashlib", "base64", "uuid", "io",
    "tempfile", "logging", "threading", "multiprocessing", "sqlite3",
    "csv", "xml", "html", "http", "urllib", "socket",
    "ssl", "email", "struct", "pickle", "copy", "pprint",
    "random", "statistics", "decimal", "fractions", "string",
    "textwrap", "codecs", "difflib", "filecmp", "glob",
    "fnmatch", "linecache", "bisect", "heapq", "array",
    "weakref", "types", "enum", "abc", "dataclasses",
    "contextlib", "warnings", "traceback", "inspect",
    "ast", "compileall", "dis", "tokenize", "keyword",
    "numbers", "cmath", "operator", "sysconfig", "platform",
    "errno", "ctypes", "signal", "mmap", "pdb", "profile",
    "unittest", "doctest", "test",
}


def _check_import_exists(package_name):
    """Check if a Python package is actually installable."""
    pkg = package_name.split('.')[0]
    
    # Known stdlib → skip checking
    if pkg in _STDLIB_MODULES:
        return True
    
    if pkg in _HALLUCINATION_CACHE:
        return _HALLUCINATION_CACHE[pkg]
    try:
        r = subprocess.run(
            [sys.executable, "-c", f"import {pkg}"],
            capture_output=True, text=True, timeout=5
        )
        exists = r.returncode == 0
        _HALLUCINATION_CACHE[pkg] = exists
        return exists
    except Exception:
        return True  # timeout → assume exists (don't block on network)


def check_ai_patterns(file_path, deep=False):
    """Scan a file for AI behavior patterns. Returns list of findings."""
    fp = Path(file_path)
    if not fp.exists():
        return []
    
    text = fp.read_text(encoding="utf-8", errors="replace")
    lines = text.split("\n")
    findings = []

    for rule in AI_PATTERNS:
        for pattern in rule["patterns"]:
            for i, line in enumerate(lines, 1):
                m = re.search(pattern, line, re.IGNORECASE)
                if m:
                    finding = {
                        "id": rule["id"],
                        "name": rule["name"],
                        "severity": rule["severity"],
                        "line": i,
                        "match": line.strip()[:100],
                        "message": rule["message"],
                        "pattern": pattern
                    }

                    # Hallucination check: skip if stdlib, verify on deep
                    if rule["id"] == "AI-HALL-001":
                        pkg = m.group(1).split('.')[0]
                        if pkg in _STDLIB_MODULES:
                            continue  # stdlib, not hallucinated
                        if deep and not _check_import_exists(pkg):
                            finding["severity"] = "error"
                            finding["message"] = f"HALLUCINATED PACKAGE: '{pkg}' not found"
                        else:
                            continue  # skip basic import detection, only flag on deep failure

                    findings.append(finding)
                    break  # one match per rule per line is enough

    # Deduplicate: keep first match per rule per line
    seen = set()
    unique = []
    for f in findings:
        key = (f["id"], f["line"])
        if key not in seen:
            seen.add(key)
            unique.append(f)
    
    return unique


def format_ai_findings(findings):
    """Pretty-print AI pattern findings."""
    if not findings:
        print("\n  ✅ No AI behavior patterns detected")
        return

    by_severity = {"error": [], "warning": [], "info": []}
    for f in findings:
        by_severity.setdefault(f["severity"], []).append(f)

    print(f"\n  🕵️  AI PATTERN ANALYSIS ({len(findings)} findings)")
    for sev in ["error", "warning", "info"]:
        items = by_severity.get(sev, [])
        if not items:
            continue
        icon = "❌" if sev == "error" else "⚠️" if sev == "warning" else "ℹ️"
        print(f"\n    {icon} {sev.upper()} ({len(items)})")
        for f in items:
            print(f"      Line {f['line']:4d}  [{f['id']}] {f['name']}")
            print(f"             {f['match'][:80]}")


# ── Framework Checkers ─────────────────────────────────────────

REACT_PATTERNS = [
    {"id": "REACT-HOOK-001", "name": "Missing useEffect dependency array", "severity": "error",
     "since": "16.8", "until": None,
     "patterns": [r"useEffect\(\s*\(\)\s*=>\s*\{",
                   r"useEffect\(\s*function\s*\("],
     "message": "useEffect without dependency array — check if [deps] is provided"},
    {"id": "REACT-KEY-001", "name": "Missing key prop in list", "severity": "warning",
     "since": "0.14", "until": None,
     "patterns": [r"\.map\(\s*(?:\(\s*\w+(?:,\s*\w+)?\s*\)|\w+)\s*=>\s*<(?!!\[CDATA)"],
     "message": "List items need a unique 'key' prop — add key={item.id}"},
    {"id": "REACT-NEXT-001", "name": "Missing 'use client' directive", "severity": "warning",
     "since": "16.8", "until": None,
     "patterns": [r"import\s+\{[^}]*use(?:State|Effect|Ref|Reducer|Callback|Memo|Context)\}"],
     "message": "Hooks in Next.js App Router need 'use client' at the top"},
    {"id": "REACT-MUT-001", "name": "Direct state mutation", "severity": "error",
     "since": "0.14", "until": None,
     "patterns": [r"\.push\(|\.splice\(", r"\.sort\("],
     "message": "Don't mutate state directly — use setState(prev => [...prev, newItem])"},
]


def check_react(file_path, version="latest"):
    fp = Path(file_path); text = fp.read_text(encoding="utf-8", errors="replace") if fp.exists() else ""
    lines = text.split("\n"); findings = []
    for rule in REACT_PATTERNS:
        if not _version_match(version, rule): continue
        for p in rule["patterns"]:
            for i, line in enumerate(lines, 1):
                if not re.search(p, line): continue
                if rule["id"] == "REACT-HOOK-001":
                    surrounding = "\n".join(lines[i:i+5])
                    if re.search(r'\}\s*,\s*\[', surrounding): continue
                if rule["id"] == "REACT-KEY-001":
                    if "key=" in line or "key={" in line: continue
                    if i < len(lines) and ("key=" in lines[i] or "key={" in lines[i]): continue
                findings.append({"id": rule["id"], "name": rule["name"], "severity": rule["severity"],
                                 "line": i, "match": line.strip()[:100], "message": rule["message"]})
                break
    return findings


EXPRESS_PATTERNS = [
    {"id": "EXP-ERR-001", "name": "Missing error handler", "severity": "error",
     "since": "4.0", "until": None,
     "patterns": [r"app\.use\(\(req,\s*res,\s*next\)\s*=>"],
     "message": "Add 4-arg error handler: app.use((err, req, res, next) => {...})"},
    {"id": "EXP-ASYNC-001", "name": "Unhandled async error", "severity": "error",
     "since": "4.0", "until": None,
     "patterns": [r"app\.(get|post|put|delete|patch)\([^)]*,\s*async\s*\("],
     "message": "Wrap async handlers: try {...} catch(next)"},
    {"id": "EXP-NEXT-001", "name": "Missing next() call", "severity": "warning",
     "since": "4.0", "until": None,
     "patterns": [r"(?<!err,)\s*app\.use\(\(req,\s*res(?:,\s*next)?\)\s*=>\s*\{"],
     "message": "Middleware should call next() or send a response"},
    {"id": "EXP-CORS-001", "name": "Overly permissive CORS", "severity": "error",
     "since": "4.0", "until": None,
     "patterns": [r'Access-Control-Allow-Origin\s*:\s*\*', r"origin\s*:\s*\*"],
     "message": "CORS * allows any site — restrict to specific origins"},
    {"id": "EXP-SQL-001", "name": "Raw SQL injection risk", "severity": "error",
     "since": "4.0", "until": None,
     "patterns": [r"SELECT\s+.*\$\{", r"`SELECT\s+.*\$\{"],
     "message": "Use parameterized queries: db.query('SELECT ...', [params])"},
]


def check_express(file_path, version="latest"):
    fp = Path(file_path); text = fp.read_text(encoding="utf-8", errors="replace") if fp.exists() else ""
    lines = text.split("\n"); findings = []
    for rule in EXPRESS_PATTERNS:
        if not _version_match(version, rule): continue
        for p in rule["patterns"]:
            for i, line in enumerate(lines, 1):
                if not re.search(p, line): continue
                if rule["id"] == "EXP-NEXT-001":
                    surrounding = "\n".join(lines[i-1:i+3])
                    if re.search(r'\bnext\(', surrounding) or re.search(r'err,', line): continue
                findings.append({"id": rule["id"], "name": rule["name"], "severity": rule["severity"],
                                 "line": i, "match": line.strip()[:100], "message": rule["message"]})
                break
    return findings


NEXT_PATTERNS = [
    {"id": "NEXT-SRV-001", "name": "Missing 'use server' directive", "severity": "error",
     "since": "13.0", "until": None,
     "patterns": [r"export\s+async\s+function\s+\w+(?:Server|Action|Form)"],
     "message": "Server actions need 'use server' directive"},
    {"id": "NEXT-META-001", "name": "Missing generateMetadata", "severity": "info",
     "since": "13.0", "until": None,
     "patterns": [r"export\s+default\s+(?:async\s+)?function\s+(?:Home|\w+Page)"],
     "message": "Consider adding generateMetadata() for SEO"},
    {"id": "NEXT-CACHE-001", "name": "No cache strategy", "severity": "info",
     "since": "13.0", "until": None,
     "patterns": [r"\bfetch\(['\"`]https?://"],
     "message": "Add revalidation: fetch(url, { next: { revalidate: 3600 } })"},
]


def check_next(file_path, version="latest"):
    fp = Path(file_path); text = fp.read_text(encoding="utf-8", errors="replace") if fp.exists() else ""
    lines = text.split("\n"); findings = []
    has_server = any("use server" in ln for ln in lines[:3])
    has_metadata = any("generateMetadata" in ln for ln in lines)
    for rule in NEXT_PATTERNS:
        if not _version_match(version, rule): continue
        for p in rule["patterns"]:
            for i, line in enumerate(lines, 1):
                if not re.search(p, line): continue
                if rule["id"] == "NEXT-SRV-001" and has_server: continue
                if rule["id"] == "NEXT-META-001" and has_metadata: continue
                if rule["id"] == "NEXT-META-001" and not any(x in text for x in ["fetch(", "getServerSideProps", "useQuery"]): continue
                findings.append({"id": rule["id"], "name": rule["name"], "severity": rule["severity"],
                                 "line": i, "match": line.strip()[:100], "message": rule["message"]})
                break
    return findings


VUE_PATTERNS = [
    {"id": "VUE-ROUTER-001", "name": "Deprecated VueRouter constructor", "severity": "error",
     "since": "3.0", "until": None,
     "patterns": [r"new\s+VueRouter\("],
     "message": "Vue 3 uses createRouter(), not new VueRouter()"},
    {"id": "VUE-THIS-001", "name": "this.$router in setup()", "severity": "error",
     "since": "3.0", "until": None,
     "patterns": [r"this\.\$router", r"this\.\$route"],
     "message": "In setup(), use useRouter() and useRoute()"},
    {"id": "VUE-GUARD-001", "name": "Deprecated next() in guards", "severity": "warning",
     "since": "3.5", "until": None,
     "patterns": [r"router\.beforeEach\(\(to,\s*from,\s*next\)"],
     "message": "Vue 3.5+: return path instead of calling next()"},
    {"id": "VUE-VFOR-001", "name": "Missing :key in v-for", "severity": "warning",
     "since": "2.0", "until": None,
     "patterns": [r"v-for\s*=\s*['\"][^'\"]*['\"]"],
     "message": "Add :key=\"item.id\" to v-for for proper reconciliation"},
]


def check_vue(file_path, version="latest"):
    fp = Path(file_path); text = fp.read_text(encoding="utf-8", errors="replace") if fp.exists() else ""
    lines = text.split("\n"); findings = []
    for rule in VUE_PATTERNS:
        if not _version_match(version, rule): continue
        for p in rule["patterns"]:
            for i, line in enumerate(lines, 1):
                if not re.search(p, line): continue
                if rule["id"] == "VUE-VFOR-001" and ":key" in line: continue
                findings.append({"id": rule["id"], "name": rule["name"], "severity": rule["severity"],
                                 "line": i, "match": line.strip()[:100], "message": rule["message"]})
                break
    return findings


LARAVEL_PATTERNS = [
    {"id": "LARA-FILL-001", "name": "Missing $fillable/$guarded", "severity": "error",
     "since": "3.0", "until": None,
     "patterns": [r"class\s+\w+\s+extends\s+Model"],
     "message": "Add protected $fillable = [...] to prevent mass assignment"},
    {"id": "LARA-ENV-001", "name": "env() called outside config", "severity": "error",
     "since": "5.0", "until": None,
     "patterns": [r"env\(['\"`]"],
     "message": "env() only works in config files — use config() elsewhere"},
    {"id": "LARA-NPLUS-001", "name": "Potential N+1 query", "severity": "warning",
     "since": "3.0", "until": None,
     "patterns": [r"@foreach\s*\([^)]*\)[^@]*{{[^}]*\->\w+\.\w+}}"],
     "message": "Eager load relationships: Model::with('relation')->get()"},
    {"id": "LARA-SQL-001", "name": "Raw SQL without binding", "severity": "error",
     "since": "3.0", "until": None,
     "patterns": [r"DB::(select|statement|unprepared)\(['\"`][^'\"]*\$\w+['\"`]"],
     "message": "Use parameter binding: DB::select('...', [$param])"},
    {"id": "LARA-VALID-001", "name": "Validation in controller", "severity": "info",
     "since": "5.0", "until": None,
     "patterns": [r"\$this->validate\(", r"Validator::make\("],
     "message": "Extract validation to a Form Request class"},
    # EOL warnings (version-specific)
    {"id": "LARA-EOL-001", "name": "Version is end-of-life", "severity": "error",
     "since": "3.0", "until": "9.9",
     "patterns": [], "eol": True,
     "message": "Laravel version is EOL — upgrade to receive security patches"},
]


def _eol_check(version_found):
    """Return EOL rules for outdated framework versions."""
    if version_found == "latest": return []
    return []


def check_laravel(file_path, version="latest"):
    fp = Path(file_path); text = fp.read_text(encoding="utf-8", errors="replace") if fp.exists() else ""
    lines = text.split("\n"); findings = []
    has_fillable = any("$fillable" in ln for ln in lines)
    for rule in LARAVEL_PATTERNS:
        if not _version_match(version, rule): continue
        for p in rule["patterns"]:
            for i, line in enumerate(lines, 1):
                if not re.search(p, line): continue
                if rule["id"] == "LARA-FILL-001" and has_fillable: continue
                findings.append({"id": rule["id"], "name": rule["name"], "severity": rule["severity"],
                                 "line": i, "match": line.strip()[:100], "message": rule["message"]})
                break
    return findings


DJANGO_PATTERNS = [
    {"id": "DJANGO-ONDEL-001", "name": "Missing on_delete", "severity": "error",
     "since": "2.0", "until": None,
     "patterns": [r"models\.(ForeignKey|OneToOneField)\("],
     "message": "Add on_delete=models.CASCADE to ForeignKey"},
    {"id": "DJANGO-DECIMAL-001", "name": "FloatField for money", "severity": "warning",
     "since": "1.0", "until": None,
     "patterns": [r"models\.FloatField"],
     "message": "Use DecimalField for currency"},
    {"id": "DJANGO-NPLUS-001", "name": "Missing select_related", "severity": "warning",
     "since": "1.0", "until": None,
     "patterns": [r"\w+\.(?:filter|all|get)\(\)\.(?:filter|order_by|exclude)"],
     "message": "Add select_related() to prevent N+1 queries"},
    {"id": "DJANGO-URL-001", "name": "URL pattern mismatch", "severity": "warning",
     "since": "2.0", "until": None,
     "patterns": [r"path\('([^']+)<(\w+):(\w+)>[^']*',"],
     "message": "Ensure URL param names match view function parameter names"},
    {"id": "DJANGO-MIGRATE-001", "name": "Hand-written migration", "severity": "warning",
     "since": "1.7", "until": None,
     "patterns": [r"class\s+Migration\s*\(.*Migration\)"],
     "message": "Use python manage.py makemigrations, not hand-written"},
]


def check_django(file_path, version="latest"):
    fp = Path(file_path); text = fp.read_text(encoding="utf-8", errors="replace") if fp.exists() else ""
    lines = text.split("\n"); findings = []
    has_on_delete = any("on_delete" in ln for ln in lines)
    for rule in DJANGO_PATTERNS:
        if not _version_match(version, rule): continue
        for p in rule["patterns"]:
            for i, line in enumerate(lines, 1):
                if not re.search(p, line): continue
                if rule["id"] == "DJANGO-ONDEL-001" and has_on_delete: continue
                if rule["id"] == "DJANGO-MIGRATE-001" and not Path(file_path).name.startswith("00"): continue
                findings.append({"id": rule["id"], "name": rule["name"], "severity": rule["severity"],
                                 "line": i, "match": line.strip()[:100], "message": rule["message"]})
                break
    return findings


SPRING_PATTERNS = [
    {"id": "SPRING-SEC-001", "name": "Deprecated WebSecurityConfigurerAdapter", "severity": "error",
     "since": "3.0", "until": None,
     "patterns": [r"extends\s+WebSecurityConfigurerAdapter"],
     "message": "Spring Boot 3+ uses SecurityFilterChain bean instead of adapter"},
    {"id": "SPRING-CORS-001", "name": "Missing CORS bean", "severity": "warning",
     "since": "2.0", "until": None,
     "patterns": [r"@CrossOrigin"],
     "message": "Define a CorsConfigurationSource bean instead"},
    {"id": "SPRING-DI-001", "name": "Missing DI annotation", "severity": "error",
     "since": "1.0", "until": None,
     "patterns": [r"class\s+\w+(Service|Repository|Component|Controller)\b"],
     "message": "Add @Service/@Repository/@Component annotation"},
    {"id": "SPRING-MVC-001", "name": "Hardcoded endpoint path", "severity": "info",
     "since": "2.0", "until": None,
     "patterns": [r'@(GetMapping|PostMapping|RequestMapping)\("([^"]*)"\)'],
     "message": "Move URL paths to application.properties"},
]


def check_spring(file_path, version="latest"):
    fp = Path(file_path); text = fp.read_text(encoding="utf-8", errors="replace") if fp.exists() else ""
    lines = text.split("\n"); findings = []
    has_annotation = any(a in text for a in ["@Service", "@Repository", "@Component", "@Controller"])
    for rule in SPRING_PATTERNS:
        if not _version_match(version, rule): continue
        for p in rule["patterns"]:
            for i, line in enumerate(lines, 1):
                if not re.search(p, line): continue
                if rule["id"] == "SPRING-DI-001" and has_annotation: continue
                findings.append({"id": rule["id"], "name": rule["name"], "severity": rule["severity"],
                                 "line": i, "match": line.strip()[:100], "message": rule["message"]})
                break
    return findings


FLUTTER_PATTERNS = [
    {"id": "FLUTTER-DISPOSE-001", "name": "Missing dispose()", "severity": "error",
     "since": "1.0", "until": None,
     "patterns": [r"(AnimationController|TextEditingController|ScrollController|TabController|PageController|FocusNode)"],
     "message": "Dispose controllers in dispose() to prevent memory leaks"},
    {"id": "FLUTTER-MOUNTED-001", "name": "setState after async without mounted", "severity": "error",
     "since": "1.0", "until": None,
     "patterns": [r"await\s+.*?\n.*setState\("],
     "message": "Check 'if (mounted)' before setState() after await"},
    {"id": "FLUTTER-CONST-001", "name": "Missing const constructor", "severity": "warning",
     "since": "1.0", "until": None,
     "patterns": [r"class\s+\w+\s+extends\s+(StatelessWidget|StatefulWidget)"],
     "message": "Add const constructor for better performance"},
    {"id": "FLUTTER-PRINT-001", "name": "print() in production code", "severity": "warning",
     "since": "1.0", "until": None,
     "patterns": [r"^\s*print\("],
     "message": "Use debugPrint() or remove before shipping"},
    {"id": "FLUTTER-ERROR-001", "name": "Image without errorBuilder", "severity": "warning",
     "since": "1.0", "until": None,
     "patterns": [r"Image\.network\("],
     "message": "Add errorBuilder to handle image load failures"},
]


def check_flutter(file_path, version="latest"):
    fp = Path(file_path); text = fp.read_text(encoding="utf-8", errors="replace") if fp.exists() else ""
    lines = text.split("\n"); findings = []
    has_dispose = any("dispose()" in ln or "super.dispose" in ln for ln in lines)
    has_const_constructor = any("const" in ln for ln in lines[:5])
    for rule in FLUTTER_PATTERNS:
        if not _version_match(version, rule): continue
        for p in rule["patterns"]:
            for i, line in enumerate(lines, 1):
                if not re.search(p, line): continue
                if rule["id"] == "FLUTTER-DISPOSE-001" and has_dispose: continue
                if rule["id"] == "FLUTTER-CONST-001" and has_const_constructor: continue
                findings.append({"id": rule["id"], "name": rule["name"], "severity": rule["severity"],
                                 "line": i, "match": line.strip()[:100], "message": rule["message"]})
                break
    return findings


# ── Version Helpers ─────────────────────────────────────────────

def _parse_version(v):
    """Parse version string to tuple for comparison."""
    from packaging.version import Version
    if v == "latest": return Version("9999.9999")
    try: return Version(v)
    except Exception: return Version("0.0")


def _version_match(version, rule):
    """Check if a rule applies to the given framework version."""
    if version == "latest": return True
    v = _parse_version(version)
    since = rule.get("since")
    until = rule.get("until")
    if since and v < _parse_version(since): return False
    if until and v > _parse_version(until): return False
    return True


def detect_version(framework, file_path=None):
    """Auto-detect framework version from project files."""
    root = Path(file_path).parent if file_path else Path(".")
    
    detectors = {
        "react": ("package.json", "react"),
        "express": ("package.json", "express"),
        "next": ("package.json", "next"),
        "vue": ("package.json", "vue"),
        "laravel": ("composer.json", "laravel/framework"),
        "django": ("requirements.txt", "django"),
        "spring": ("pom.xml", "spring-boot-starter-parent"),
        "flutter": ("pubspec.yaml", "sdk"),
    }
    
    filename, pkg = detectors.get(framework, ("package.json", ""))
    target = root / filename
    
    if not target.exists():
        # Walk up directories
        for parent in root.parents:
            target = parent / filename
            if target.exists(): break
    
    if not target.exists():
        return "latest"
    
    try:
        if filename == "package.json":
            data = json.loads(target.read_text())
            deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
            v = deps.get(pkg, "")
            return re.sub(r'[\^~>=<\s]', '', v).split(".")[0] if v else "latest"
        elif filename == "composer.json":
            data = json.loads(target.read_text())
            require = data.get("require", {})
            v = require.get(pkg, "")
            return re.sub(r'[\^~>=<\s]', '', v).split(".")[0] if v else "latest"
        elif filename == "requirements.txt":
            for line in target.read_text().split("\n"):
                if line.lower().startswith("django") and "=" in line:
                    v = line.split("=")[-1].strip()
                    return v.split(".")[0]
        elif filename == "pom.xml":
            m = re.search(r'<spring-boot.version>([^<]+)</spring-boot.version>', target.read_text())
            if m: return m.group(1).split(".")[0]
        elif filename == "pubspec.yaml":
            m = re.search(r'sdk:\s*">?=?([^"\n]+)', target.read_text())
            if m: return "3" if "3" in m.group(1) else "2"
    except Exception:
        pass
    return "latest"


def generate_migration_plan(framework, from_version, to_version):
    """Generate upgrade steps between versions."""
    plans = {
        "laravel": {
            ("3", "4"): ["Add namespaces to all classes", "Update routes.php syntax", "Replace Blade @yield with @section"],
            ("4", "5"): ["Add $fillable to all models", "Replace Form Builder with Form Requests", "Add Http/Kernel.php", "Update service providers"],
            ("5", "6"): ["Replace env() with config() outside config files", "Update to latest LTS"],
            ("6", "7"): ["Update to Laravel 7 dependencies", "Check for deprecated helpers"],
            ("7", "8"): ["Replace deprecated helpers with Facades", "Update Blade components"],
            ("8", "9"): ["PHP 8.0+ required", "Update to Symfony 6 components"],
            ("9", "10"): ["PHP 8.1+ required", "Update type hints in all signatures"],
            ("10", "11"): ["PHP 8.2+ required", "Slimmed application skeleton", "Consolidated config files"],
            ("11", "12"): ["Minor — check for deprecated methods"],
            ("12", "13"): ["PHP 8.3+ required", "Update to Laravel 13 dependencies"],
        },
        "django": {
            ("1", "2"): ["Python 3+ required — remove Python 2 compatibility", "Replace url() with path()"],
            ("2", "3"): ["ASGI configuration required", "Add default_auto_field to AppConfig"],
            ("3", "4"): ["Add apps.py for each app", "Update timezone handling"],
            ("4", "5"): ["Python 3.10+ required", "Update psycopg2 to psycopg3"],
        },
        "spring": {
            ("1", "2"): ["Update to Spring Boot 2 parent", "Replace WebSecurityConfigurerAdapter with SecurityFilterChain"],
            ("2", "3"): ["Java 17+ required", "Replace javax.* with jakarta.*", "Remove deprecated WebMvcConfigurerAdapter"],
        },
        "vue": {
            ("2", "3"): ["Replace VueRouter() with createRouter()", "Replace options API with Composition API", "Remove filters and event bus"],
            ("3", "3.5"): ["Replace next() in guards with return path", "Update to new Vite template"],
        },
        "react": {
            ("16.8", "18"): ["Update to createRoot API (React 18)", "Enable StrictMode", "Check for legacy lifecycle patterns"],
            ("18", "19"): ["React Compiler stable", "Check for removed APIs"],
        },
        "flutter": {
            ("1", "2"): ["Null safety required — massive migration", "Use ?, ??, ! operators", "Run dart migrate"],
            ("2", "3"): ["Material 3", "Check for deprecated widgets"],
        },
    }
    
    fw_plans = plans.get(framework, {})
    steps = []
    # Convert "3" and "4" to comparable
    for (f, t), s in sorted(fw_plans.items()):
        fv = _parse_version(f)
        tv = _parse_version(t)
        if fv >= _parse_version(from_version) and tv <= _parse_version(to_version):
            steps.append({"from": f, "to": t, "steps": s})
    
    # Sort by from_version numerically
    steps.sort(key=lambda x: _parse_version(x["from"]))
    
    return steps


def format_migration_plan(plan, framework):
    """Pretty-print migration plan."""
    if not plan:
        print(f"\n  ✅ {framework} is already at the target version")
        return
    print(f"\n  📋 {framework.upper()} MIGRATION PLAN")
    print(f"  {'='*50}")
    for phase in plan:
        print(f"\n  Phase: {phase['from']} → {phase['to']}")
        for step in phase['steps']:
            print(f"    • {step}")


def format_framework_findings(findings, framework="React"):
    """Pretty-print framework pattern findings."""
    if not findings:
        print(f"\n  ✅ No {framework} pattern violations")
        return
    by_severity = {"error": [], "warning": [], "info": []}
    for f in findings:
        by_severity.setdefault(f["severity"], []).append(f)
    icons = {"error": "❌", "warning": "⚠️", "info": "ℹ️"}
    print(f"\n  ⚛️  {framework.upper()} PATTERN ANALYSIS ({len(findings)} findings)")
    for sev in ["error", "warning", "info"]:
        items = by_severity.get(sev, [])
        if not items: continue
        print(f"\n    {icons[sev]} {sev.upper()} ({len(items)})")
        for f in items:
            print(f"      Line {f['line']:4d}  [{f['id']}] {f['name']}")
            print(f"             {f['message'][:80]}")
            print(f"             → {f['match'][:60]}")


FRAMEWORK_CHECKERS = {
    "react": check_react, "express": check_express, "next": check_next,
    "vue": check_vue, "laravel": check_laravel, "django": check_django,
    "spring": check_spring, "flutter": check_flutter,
}


def check_framework(file_path, framework, version="latest"):
    """Dispatch to the correct framework checker with version."""
    checker = FRAMEWORK_CHECKERS.get(framework)
    if not checker: return []
    return checker(file_path, version=version)


# ── Phase 6: Live Quality Score ────────────────────────────────

def calculate_score(fp):
    """Run validation + AI check, return a 0-100 quality score."""
    deductions = 0
    
    # 1. Gate validation (max 60 points)
    cfg = load_config()
    ok, results = validate_file(fp, cfg)
    if not ok:
        failed = sum(1 for v in results.values() if not v["pass"])
        deductions += failed * 20  # -20 per failed check
    
    # 2. AI patterns (max 30 points)
    findings = check_ai_patterns(fp, deep=False)
    error_count = sum(1 for f in findings if f["severity"] == "error")
    warning_count = sum(1 for f in findings if f["severity"] == "warning")
    deductions += error_count * 15  # -15 per AI error
    deductions += warning_count * 5  # -5 per AI warning
    
    # 3. File size sanity (max 10 points)
    try:
        size = Path(fp).stat().st_size
        if size > 500000:  # >500KB
            deductions += 5
    except Exception:
        pass
    
    score = max(0, 100 - deductions)
    return score


def score_to_grade(score):
    """Convert 0-100 score to letter grade."""
    if score >= 90: return "A", "✅ Excellent"
    if score >= 80: return "B", "✅ Good"
    if score >= 60: return "C", "⚠️  Needs work"
    if score >= 40: return "D", "⚠️  Poor"
    return "F", "❌ Failing"


def format_score(score, grade, label, fp):
    """Pretty-print score."""
    bar_len = ord(grade) - ord('A') if grade in "ABCDF" else 4
    bar = "█" * (20 - bar_len * 5) + "░" * (bar_len * 5)
    
    print(f"\n  📊 QUALITY SCORE — {Path(fp).name}")
    print(f"  {bar} {score:3d}/100 ({grade}) {label}")
    
    if score >= 90:
        print("     Ship it! 🚀")
    elif score >= 80:
        print("     Minor improvements recommended")
    elif score >= 60:
        print("     Review flagged issues before shipping")
    elif score >= 40:
        print("     Significant issues — fix before merge")
    else:
        print("     Blocked — must fix before shipping")


def dashboard_live(fp, refresh=3):
    """Live-updating terminal dashboard."""
    from rich.live import Live
    from rich.table import Table
    from rich.console import Console
    
    console = Console()
    
    with Live(refresh_per_second=1 / refresh, console=console) as live:
        while True:
            try:
                score = calculate_score(fp)
                grade, label = score_to_grade(score)
                cfg = load_config()
                ok, results = validate_file(fp, cfg)
                ai_findings = check_ai_patterns(fp)
                
                table = Table(title=f"🚪 Maya Gate — {Path(fp).name}")
                table.add_column("Check", style="cyan")
                table.add_column("Result", style="green")
                table.add_column("Detail")
                
                for check, data in results.items():
                    icon = "✅" if data["pass"] else "❌"
                    table.add_row(check, icon, data["detail"][:50])
                
                table.add_row("AI Patterns", 
                              f"{len(ai_findings)} found",
                              f"{sum(1 for f in ai_findings if f['severity']=='error')} errors")
                
                table.add_row("Score", f"{grade} ({score}/100)", label)
                
                live.update(table)
                
                import time
                time.sleep(refresh)
            except KeyboardInterrupt:
                break
            except Exception as e:
                live.update(Table(title=f"⚠️ Error: {e}"))
                break


# ── Stats ──────────────────────────────────────────────────────

def query_stats(since="7d", by_language=False, by_framework=False):
    """Query validation statistics from PostgreSQL."""
    from db import pg_query, USE_PG
    
    if not USE_PG:
        return {"error": "USE_POSTGRES not enabled - set USE_POSTGRES=true"}
    
    days = {"1d": 1, "7d": 7, "30d": 30, "all": 9999}.get(since, 7)
    date_filter = f"AND time_created >= NOW() - INTERVAL '{days} days'" if days < 9999 else ""
    
    result = {}
    
    # Total checks
    rows = pg_query(f"""
        SELECT COUNT(*) as total,
               COUNT(*) FILTER (WHERE cost > 0) as paid,
               COUNT(*) FILTER (WHERE cost = 0 OR cost IS NULL) as free
        FROM prima_niaga.opencode_messages
        WHERE agent IS NOT NULL {date_filter}
    """)
    if rows:
        result["total"] = int(rows[0][0] or 0)
        result["paid"] = int(rows[0][1] or 0)
        result["free"] = int(rows[0][2] or 0)
    
    # Total cost
    rows = pg_query(f"""
        SELECT ROUND(SUM(cost)::numeric, 2) FROM prima_niaga.opencode_messages
        WHERE agent IS NOT NULL {date_filter}
    """)
    if rows:
        result["total_cost"] = float(rows[0][0] or 0)
    
    # Sessions
    rows = pg_query(f"""
        SELECT COUNT(DISTINCT session_id) FROM prima_niaga.opencode_messages
        WHERE agent IS NOT NULL {date_filter}
    """)
    if rows:
        result["sessions"] = int(rows[0][0] or 0)
    
    # By agent
    rows = pg_query(f"""
        SELECT agent, COUNT(*) as c, ROUND(AVG(cost)::numeric, 4) as avg
        FROM prima_niaga.opencode_messages
        WHERE agent IS NOT NULL {date_filter}
        GROUP BY agent ORDER BY c DESC
    """)
    if rows:
        result["by_agent"] = {r[0]: {"count": int(r[1]), "avg_cost": float(r[2] or 0)} for r in rows}
    
    # By model group
    rows = pg_query(f"""
        SELECT 
            CASE 
                WHEN model LIKE '%deepseek-v4-flash%' AND model NOT LIKE '%free%' THEN 'DeepSeek V4 Flash'
                WHEN model LIKE '%deepseek-v4-pro%' THEN 'DeepSeek V4 Pro'
                WHEN model LIKE '%free%' THEN 'DeepSeek Flash Free'
                WHEN model LIKE '%claude%' THEN 'Claude'
                WHEN model LIKE '%gpt%' THEN 'GPT'
                WHEN model LIKE '%ollama%' OR model LIKE '%qwen%' THEN 'Local (Ollama)'
                ELSE 'Other'
            END as model_group,
            COUNT(*) as c
        FROM prima_niaga.opencode_messages
        WHERE agent IS NOT NULL {date_filter}
        GROUP BY model_group ORDER BY c DESC
    """)
    if rows:
        result["by_model"] = {r[0]: int(r[1]) for r in rows}
    
    # Daily trend (last 7 days)
    rows = pg_query(f"""
        SELECT date(time_created) as d, COUNT(*), ROUND(SUM(cost)::numeric, 2)
        FROM prima_niaga.opencode_messages
        WHERE agent IS NOT NULL {date_filter}
        GROUP BY d ORDER BY d
    """)
    if rows:
        result["daily_trend"] = {str(r[0]): {"count": int(r[1]), "cost": float(r[2] or 0)} for r in rows}
    
    return result


# ── Convention Checker ─────────────────────────────────────────

CONVENTION_DIR = Path.home() / ".config/maya-gate/conventions"

CONVENTION_SOURCES = {
    "python": "https://raw.githubusercontent.com/github/awesome-copilot/main/instructions/dataverse-python.instructions.md",
    "testing": "https://raw.githubusercontent.com/github/awesome-copilot/main/instructions/nodejs-javascript-vitest.instructions.md",
    "git": "https://raw.githubusercontent.com/github/awesome-copilot/main/instructions/github-actions-ci-cd-best-practices.instructions.md",
}

# Positive rules: code SHOULD have these patterns
_POSITIVE_RULES = {
    "async/await": {"pattern": r"\basync\b|\bawait\b"},
    "type hints": {"pattern": r":\s*(?:str|int|float|bool|list|dict|tuple|set|Any|Optional|Union)\b|->\s*\w"},
    "const/let": {"pattern": r"\bconst\b|\blet\b"},
    "error handling": {"pattern": r"\btry\b|\bexcept\b|\braise\b"},
    "f-strings": {"pattern": r"f['\"]"},
    "docstrings": {"pattern": r'""".*?"""|\'\'\'.*?\'\'\''},
    "imports first": {"pattern": r"^import\s|^from\s"},
    "function naming": {"pattern": r"^def\s+[a-z_][a-z0-9_]*\b"},
    "class naming": {"pattern": r"^class\s+[A-Z]"},
}

# Negative rules: code should NOT have these patterns
_NEGATIVE_RULES = {
    "null": {"pattern": r"\bnull\b"},
    "var keyword": {"pattern": r"\bvar\b"},
    "console.log": {"pattern": r"console\.log\b"},
    "TODO/FIXME": {"pattern": r"TODO|FIXME|XXX"},
    "bare except": {"pattern": r"\bexcept\s*:"},
}


def _load_conventions(framework="python"):
    """Load a convention .md file and extract checkable rules."""
    path = CONVENTION_DIR / f"{framework}.md"
    if not path.exists():
        return []
    
    text = path.read_text()
    rules = []
    current_section = None
    rule_id = 0

    for line in text.split("\n"):
        if line.startswith("## "):
            current_section = line.strip("# ")
        elif line.strip().startswith("- ") and current_section:
            rule_text = line.strip("- ")
            rule_id += 1

            rule_type = None
            for keyword, check in {**_POSITIVE_RULES, **_NEGATIVE_RULES}.items():
                if keyword.lower() in rule_text.lower():
                    rule_type = {
                        "id": f"CONV-{rule_id:03d}",
                        "section": current_section,
                        "text": rule_text,
                        "pattern": check["pattern"],
                        "positive": keyword in _POSITIVE_RULES,
                    }
                    break

            if not rule_type:
                rule_type = {
                    "id": f"CONV-{rule_id:03d}",
                    "section": current_section,
                    "text": rule_text,
                    "pattern": None,
                    "positive": None,
                }

            rules.append(rule_type)

    return rules


def list_conventions():
    """List available convention files."""
    CONVENTION_DIR.mkdir(parents=True, exist_ok=True)
    files = []
    for f in sorted(CONVENTION_DIR.glob("*.md")):
        rules = _load_conventions(f.stem)
        files.append({"name": f.stem, "rules": len(rules),
                      "path": str(f), "size": f.stat().st_size})
    return files


def sync_conventions():
    """Download latest conventions from awesome-copilot repo."""
    import urllib.request
    CONVENTION_DIR.mkdir(parents=True, exist_ok=True)
    count = 0
    errors = []

    for name, url in CONVENTION_SOURCES.items():
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Maya-Gate/2.0"})
            data = urllib.request.urlopen(req, timeout=10).read().decode()
            (CONVENTION_DIR / f"{name}.md").write_text(data)
            count += 1
        except Exception as e:
            errors.append(f"{name}: {e}")

    return count, errors


def check_conventions(file_path, framework="python"):
    """Check a file against convention rules."""
    rules = _load_conventions(framework)
    if not rules:
        return []

    try:
        code = Path(file_path).read_text(encoding="utf-8", errors="replace")
    except Exception:
        return []

    findings = []

    for rule in rules:
        if rule["pattern"] is None:
            continue

        if rule["positive"]:
            # Code SHOULD have this pattern — flag if missing
            if not re.search(rule["pattern"], code):
                findings.append({
                    "id": rule["id"],
                    "section": rule["section"],
                    "severity": "info",
                    "message": f"Missing: {rule['text']}",
                    "line": 0,
                })
        else:
            # Code should NOT have this pattern — flag if present
            for i, line in enumerate(code.split("\n"), 1):
                if re.search(rule["pattern"], line):
                    findings.append({
                        "id": rule["id"],
                        "section": rule["section"],
                        "severity": "info",
                        "message": f"Avoid: {rule['text']}",
                        "line": i,
                        "match": line.strip()[:80],
                    })
                    break

    return findings


def format_convention_findings(findings, framework="python"):
    """Pretty-print convention analysis."""
    if not findings:
        print(f"\n  ✅ No convention violations ({framework})")
        return

    by_section = {}
    for f in findings:
        by_section.setdefault(f["section"], []).append(f)

    print(f"\n  📋 CONVENTION ANALYSIS ({len(findings)} findings, {framework})")
    for section, items in by_section.items():
        print(f"\n    [{section}]")
        for f in items:
            match = f" → {f['match']}" if f.get('match') else ""
            line = f" (L{f['line']})" if f['line'] else ""
            print(f"      ℹ️  {f['message']}{line}{match}")


# ── DLP Scanner ────────────────────────────────────────────────

DLP_PATTERNS = [
    {"id": "DLP-OPENAI-KEY", "name": "OpenAI/DeepSeek API key",
     "severity": "error",
     "pattern": r"sk-[A-Za-z0-9\-_]{20,}"},
    {"id": "DLP-DEEPSEEK-KEY", "name": "DeepSeek API key (native)",
     "severity": "error",
     "pattern": r"(sk|ds)-[A-Za-z0-9\-_]{20,}"},
    {"id": "DLP-GITHUB-TOKEN", "name": "GitHub token",
     "severity": "error",
     "pattern": r"gh[pousr]_[A-Za-z0-9]{36,}"},
    {"id": "DLP-AWS-KEY", "name": "AWS access key",
     "severity": "error",
     "pattern": r"AKIA[0-9A-Z]{16}"},
    {"id": "DLP-SSH-KEY", "name": "Private key",
     "severity": "blocking",
     "pattern": r"-----BEGIN [A-Z ]+KEY-----"},
    {"id": "DLP-PASSWORD", "name": "Hardcoded password",
     "severity": "warning",
     "pattern": r"(?i)(password|passwd|pwd|secret)['\"]?\s*[:=]\s*['\"][^'\"]{6,}['\"]"},
    {"id": "DLP-CONNECTION-STRING", "name": "Connection string with credentials",
     "severity": "warning",
     "pattern": r"(postgresql|mysql|mongodb|redis|sqlite)://[^:]+:[^@]+@"},
    {"id": "DLP-JWT", "name": "JWT token",
     "severity": "warning",
     "pattern": r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"},
    {"id": "DLP-GENERIC-SECRET", "name": "Generic secret/key assignment",
     "severity": "warning",
     "pattern": r"(?i)(api[_-]?key|secret[_-]?key|auth[_-]?token|access[_-]?key)\s*[:=]\s*['\"][A-Za-z0-9\-_]{20,}['\"]"},
]

def check_dlp(file_path):
    """Scan a file for hardcoded secrets and credentials."""
    fp = Path(file_path)
    if not fp.exists():
        return []
    try:
        text = fp.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return []
    
    findings = []
    lines = text.split("\n")
    
    for rule in DLP_PATTERNS:
        for i, line in enumerate(lines, 1):
            m = re.search(rule["pattern"], line)
            if not m:
                continue
            # Skip test files and example/dummy data
            if "test" in fp.stem.lower() or "example" in fp.stem.lower() or ".env." in str(fp):
                if rule["severity"] != "blocking":
                    continue
            # Skip known test patterns
            if "sk-test" in line or "sk-your-key" in line or "your-api-key" in line:
                continue
            
            findings.append({
                "id": rule["id"],
                "name": rule["name"],
                "severity": rule["severity"],
                "line": i,
                "match": line.strip()[:100],
            })
            break
    
    return findings

def format_dlp_findings(findings):
    """Pretty-print DLP scan results."""
    if not findings:
        print("\n  ✅ No secrets detected")
        return
    
    by_sev = {"blocking": [], "error": [], "warning": []}
    for f in findings:
        by_sev.setdefault(f["severity"], []).append(f)
    
    print(f"\n  🔒 DLP SCAN ({len(findings)} finding(s))")
    for sev in ["blocking", "error", "warning"]:
        items = by_sev.get(sev, [])
        if not items:
            continue
        icon = {"blocking": "🚫", "error": "❌", "warning": "⚠️"}[sev]
        label = {"blocking": "BLOCKING", "error": "ERROR", "warning": "WARNING"}[sev]
        print(f"\n    {icon} {label} ({len(items)})")
        for f in items:
            print(f"      L{f['line']:4d}  [{f['id']}] {f['name']}")
            print(f"             {f['match']}")


# ── A/B Comparison (scientist pattern) ─────────────────────────

def compare_files(old_path, new_path):
    """Compare validation results between old (control) and new (candidate) code.
    Always returns the old file's result as truth. Reports differences."""
    
    from maya_gate_lib import (validate_file, load_config, calculate_score, score_to_grade,
                                check_dlp, check_ai_patterns)
    
    cfg = load_config()
    old = Path(old_path)
    new = Path(new_path)
    
    if not old.exists():
        return {"error": f"Control file not found: {old_path}"}
    if not new.exists():
        return {"error": f"Candidate file not found: {new_path}"}
    
    def run_all_checks(fp):
        ok, results = validate_file(str(fp), cfg)
        score = calculate_score(str(fp))
        grade, label = score_to_grade(score)
        dlp = check_dlp(str(fp))
        ai = check_ai_patterns(str(fp))
        
        return {
            "pass": ok,
            "score": score,
            "grade": grade,
            "label": label,
            "dlp_count": len(dlp),
            "dlp_blocking": sum(1 for f in dlp if f["severity"] == "blocking"),
            "ai_patterns": len(ai),
            "size": fp.stat().st_size,
            "checks": {k: v["pass"] for k, v in results.items()}
        }
    
    control = run_all_checks(old)
    candidate = run_all_checks(new)
    
    # Calculate diffs
    diff = {
        "score": candidate["score"] - control["score"],
        "dlp_count": candidate["dlp_count"] - control["dlp_count"],
        "ai_patterns": candidate["ai_patterns"] - control["ai_patterns"],
    }
    
    # Scientist rule: always return control as truth, show diff
    verdict = "same"
    if diff["score"] < -5:
        verdict = "regression"
    elif diff["score"] > 5:
        verdict = "improvement"
    if diff["dlp_count"] > 0:
        verdict = "regression"
    
    return {
        "control": {**control, "path": str(old)},
        "candidate": {**candidate, "path": str(new)},
        "diff": diff,
        "verdict": verdict,
    }


def format_comparison(result):
    """Pretty-print A/B comparison results."""
    if "error" in result:
        print(f"\n  ❌ {result['error']}")
        return
    
    c = result["control"]
    n = result["candidate"]
    d = result["diff"]
    
    ver = result["verdict"]
    
    print("\n  🧪 A/B COMPARISON")
    print(f"  {'='*55}")
    print(f"  Control:   {c['path']:30s} ✅ Score: {c['score']}/100 ({c['grade']})")
    print(f"  Candidate: {n['path']:30s} {'⚠️' if ver=='regression' else '✅'} Score: {n['score']}/100 ({n['grade']})")
    print(f"  {'='*55}")
    print(f"  {'Check':<20s} {'Control':<12s} {'Candidate':<12s} {'Δ':<8s}")
    print(f"  {'─'*52}")
    print(f"  {'Syntax':<20s} {'✅' if c['checks'].get('syntax') else '❌':<12s} {'✅' if n['checks'].get('syntax') else '❌':<12s} {'—':<8s}")
    print(f"  {'Ruff':<20s} {'✅' if c['checks'].get('ruff') else '❌':<12s} {'✅' if n['checks'].get('ruff') else '❌':<12s} {'—':<8s}")
    print(f"  {'DLP findings':<20s} {c['dlp_count']:<12d} {n['dlp_count']:<12d} {'+' if d['dlp_count']>0 else ''}{d['dlp_count']:<7d} {'⚠️' if d['dlp_count']>0 else ''}")
    print(f"  {'AI patterns':<20s} {c['ai_patterns']:<12d} {n['ai_patterns']:<12d} {'+' if d['ai_patterns']>0 else ''}{d['ai_patterns']:<7d}")
    print(f"  {'Score':<20s} {c['score']:<12d} {n['score']:<12d} {'+' if d['score']>0 else ''}{d['score']:<7d}")
    print(f"  {'='*55}")
    
    if ver == "regression":
        print("\n  ❌ VERDICT: Candidate has regressions. Keeping control.")
        if d["dlp_count"] > 0:
            print(f"     Candidate introduces {d['dlp_count']} new DLP finding(s)")
    elif ver == "improvement":
        print(f"\n  ✅ VERDICT: Candidate improves score by {d['score']} points")
    else:
        print("\n  ✅ VERDICT: Candidate is equivalent to control")


# ── Approval Gates ─────────────────────────────────────────────

GATE_DIR = Path.home() / ".maya-gate/gates"
GATE_LEVELS = {"info": 0, "warning": 1, "blocking": 2}

BUILTIN_GATES = [
    {"id": "GATE-MANIFEST", "name": "Skill integrity check",
     "level": "blocking", "auto_pass": True,
     "message": "Skill integrity manifests changed — verify INTEGRITY.json"},
    {"id": "GATE-PUSH", "name": "Push protection",
     "level": "warning", "auto_pass": False,
     "message": "Staged files contain {n} change(s) — review"},
    {"id": "GATE-COST", "name": "API cost check",
     "level": "warning", "auto_pass": False,
     "message": "Estimated cost ${cost} — approve to continue"},
    {"id": "GATE-NETWORK", "name": "Network access",
     "level": "blocking", "auto_pass": False,
     "message": "Agent requesting access to {domain}"},
]


class Gate:
    """A single approval gate instance."""

    def __init__(self, gate_id, name, level, message, auto_pass=False):
        self.id = gate_id
        self.name = name
        self.level = level
        self.message = message
        self.auto_pass = auto_pass
        self.status = "pending"  # pending, approved, skipped, blocked
        self.reason = ""
        self.timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()

    def to_dict(self):
        return {"id": self.id, "name": self.name, "level": self.level,
                "message": self.message, "auto_pass": self.auto_pass,
                "status": self.status, "reason": self.reason,
                "timestamp": self.timestamp}


def create_gate(gate_id, **overrides):
    """Create a gate instance from a built-in definition."""
    config = next((g for g in BUILTIN_GATES if g["id"] == gate_id), None)
    if not config:
        return None
    g = Gate(gate_id, config["name"], config["level"],
             config["message"], config.get("auto_pass", False))
    for k, v in overrides.items():
        setattr(g, k, v)
    return g


def save_gate(gate):
    """Save gate to disk."""
    GATE_DIR.mkdir(parents=True, exist_ok=True)
    path = GATE_DIR / f"{gate.id}.json"
    path.write_text(json.dumps(gate.to_dict(), indent=2) + "\n")


def load_gate(gate_id):
    """Load gate from disk."""
    path = GATE_DIR / f"{gate_id}.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text())
    g = Gate(data["id"], data["name"], data["level"], data["message"])
    g.__dict__.update(data)
    return g


def list_gates():
    """List all pending gates."""
    GATE_DIR.mkdir(parents=True, exist_ok=True)
    gates = []
    for f in sorted(GATE_DIR.glob("*.json")):
        gate = load_gate(f.stem)
        if gate:
            gates.append(gate)
    return gates


def approve_gate(gate_id, reason=""):
    """Approve or skip a gate."""
    gate = load_gate(gate_id)
    if not gate:
        return False, f"Gate {gate_id} not found"
    if gate.status != "pending":
        return False, f"Gate {gate_id} already {gate.status}"
    gate.status = "approved"
    gate.reason = reason
    gate.timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
    save_gate(gate)
    return True, f"Gate {gate_id} approved"


def skip_gate(gate_id, reason=""):
    """Skip a warning-level gate."""
    gate = load_gate(gate_id)
    if not gate:
        return False, f"Gate {gate_id} not found"
    if gate.level == "blocking":
        return False, f"Gate {gate_id} is blocking — cannot skip"
    if gate.status != "pending":
        return False, f"Gate {gate_id} already {gate.status}"
    gate.status = "skipped"
    gate.reason = reason
    save_gate(gate)
    return True, f"Gate {gate_id} skipped"


def check_gates():
    """Run auto-pass checks and return pending blocking gates."""
    pending = []
    for config in BUILTIN_GATES:
        gate = load_gate(config["id"])
        if not gate:
            gate = create_gate(config["id"])
            save_gate(gate)

        if gate.status != "pending":
            continue
        if gate.auto_pass:
            gate.status = "approved"
            gate.reason = "Auto-pass"
            save_gate(gate)
            continue
        pending.append(gate)

    return pending


def format_gate(gate):
    """Format a single gate for display."""
    status_icons = {"pending": "⏳", "approved": "✅", "skipped": "⏭️", "blocked": "❌"}
    icon = status_icons.get(gate.status, "❓")
    level_icon = "🔴" if gate.level == "blocking" else "🟡" if gate.level == "warning" else "🔵"
    reason_str = f" — {gate.reason}" if gate.reason else ""
    return f"  {icon} {level_icon} [{gate.id}] {gate.name}\n     {gate.message}{reason_str}"


def format_gates(gates):
    """Format all gates for display."""
    if not gates:
        return "\n  ✅ No pending gates"
    lines = ["\n  🚪 APPROVAL GATES"]
    for g in gates:
        lines.append("")
        lines.append(format_gate(g))
    return "\n".join(lines) + "\n"


# ── Workflow Runner ────────────────────────────────────────────

WORKFLOW_DIR = Path(".maya-gate/workflows")


def run_workflow(workflow_path):
    """Parse and execute a markdown workflow with gates."""
    path = Path(workflow_path)
    if not path.exists():
        return False, f"Workflow not found: {workflow_path}"

    text = path.read_text()

    # Parse YAML frontmatter (simple parser)
    steps = []
    current_step = None
    in_frontmatter = text.startswith("---")
    frontmatter_lines = []
    mode = "frontmatter" if in_frontmatter else "body"

    for line in text.split("\n"):
        if mode == "frontmatter":
            if line.strip() == "---" and len(frontmatter_lines) > 0:
                mode = "body"
                continue
            frontmatter_lines.append(line)
            continue

        if line.startswith("## Step"):
            if current_step:
                steps.append(current_step)
            current_step = {"title": line.strip("# "), "commands": []}
        elif current_step and line.strip().startswith("```"):
            continue  # Skip code fences
        elif current_step and line.strip():
            current_step["commands"].append(line.strip())

    if current_step:
        steps.append(current_step)

    # Parse gates from frontmatter
    frontmatter = {}
    for line in frontmatter_lines:
        if ":" in line:
            k, v = line.split(":", 1)
            frontmatter[k.strip()] = v.strip()

    gate_ids = []
    if "gates" in frontmatter:
        import ast
        raw = frontmatter["gates"]
        try:
            gate_ids = ast.literal_eval(raw)
        except Exception:
            # Handle various formats: [A, B] or "A", "B" or A, B
            gate_ids = [g.strip(" []'\"") for g in raw.replace(",", " ").split()]

    # Register gates
    for gid in gate_ids:
        gate = create_gate(gid.strip())
        if gate:
            save_gate(gate)

    result = {
        "name": frontmatter.get("name", path.stem),
        "agent": frontmatter.get("agent", "maya"),
        "gates": gate_ids,
        "steps": steps,
    }

    return True, result
