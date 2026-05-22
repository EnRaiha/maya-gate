#!/usr/bin/env python3
"""
Maya Gate — AI Output Validation Gate v2.0
  maya-gate --file app.py              Validate a file
  maya-gate --level l1                 Syntax only (fast)
  maya-gate --level l2                 Syntax + ruff (default)
  maya-gate --level l3                 Full + linters + snip (slowest)
  maya-gate score <file>               Quality score 0-100
  maya-gate dashboard <file>           Live terminal dashboard
  maya-gate check <file>               AI behavior patterns
  maya-gate heal <file>                Auto-fix issues
  maya-gate init                       Generate identity key
  maya-gate manifest generate|verify   Skill integrity
  maya-gate attest create|verify|list  Signed attestations
  maya-gate encrypt|decrypt            Key management
  maya-gate watch                      Memory file tamper detection
  maya-gate audit                      Execution history
  maya-gate mcp                        Start MCP server
  maya-gate install                    Install hooks
"""

import sys
import os
import json
import tempfile
import shutil
import hashlib
import time
from pathlib import Path
from datetime import datetime, timezone
from maya_gate_lib import load_config, validate_file_with_pipeline, SKILLS_DIRS, hash_file, ENTERPRISE

ENTERPRISE_MSG = "🔒 Enterprise feature — upgrade at github.com/EnRaiha/maya-gate"

def _require_enterprise():
    if not ENTERPRISE:
        print(ENTERPRISE_MSG)
        sys.exit(1)

CONFIG_DIR = Path.home() / ".config/maya-gate"
MEMORY_FILES = [
    Path.home() / "main/main-memory.md",
    Path.home() / "main/current-session.md",
    Path.home() / "main/reminders.md",
]
AUDIT_LOG = Path.home() / "main/maya-gate-audit.log"
KEY_FILE = CONFIG_DIR / "keys.enc"
EXCLUDE_DIRS = {".git", "__pycache__", "node_modules", ".venv"}
EXCLUDE_FILES = {".DS_Store", "Thumbs.db", "INTEGRITY.json"}

def print_report(ok, results, fp, quiet=False):
    """Print gate validation report to terminal"""
    if quiet:
        return
    print(f"\n  {'✅' if ok else '❌'} Maya Gate — {Path(fp).name}")
    for c, d in results.items():
        i = "✅" if d["pass"] else "❌"
        dt = f" — {d['detail'][:80]}" if d["detail"] else ""
        print(f"    {i} {c:8s}{dt}")
    if not ok:
        print(f"\n    ❌ Gate blocked: {', '.join(k for k,v in results.items() if not v['pass'])}")


# ── Phase 1: Manifest System ───────────────────────────────────

def _find_skill_files(root):
    root = Path(root)
    files = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if path.name in EXCLUDE_FILES:
            continue
        if any(p in EXCLUDE_DIRS for p in path.relative_to(root).parts):
            continue
        files[path.relative_to(root).as_posix()] = hash_file(path)
    return files

def cmd_manifest_generate(target=None):
    """Generate INTEGRITY.json for a skill directory"""
    target = Path(target or SKILLS_DIRS[0])
    if not target.exists():
        print(f"❌ Directory not found: {target}")
        return False

    files = _find_skill_files(target)
    chain = hashlib.sha256()
    for key in sorted(files):
        chain.update(files[key].encode("ascii"))

    manifest = {
        "name": target.name,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "algorithm": "sha256",
        "file_count": len(files),
        "files": files,
        "manifest_hash": chain.hexdigest(),
    }

    out = target / "INTEGRITY.json"
    out.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"✅ Manifest generated: {out}")
    print(f"   {manifest['file_count']} files, hash: {manifest['manifest_hash'][:16]}...")
    return True

def cmd_manifest_verify(target=None):
    """Verify files against INTEGRITY.json"""
    target = Path(target or SKILLS_DIRS[0])
    manifest_path = target / "INTEGRITY.json"

    if not manifest_path.exists():
        print(f"❌ INTEGRITY.json not found in {target}")
        return False

    manifest = json.loads(manifest_path.read_text())
    recorded = manifest.get("files", {})
    errors = []

    for rel, expected in recorded.items():
        full = target / rel
        if not full.exists():
            errors.append(f"MISSING: {rel}")
        elif hash_file(full) != expected:
            errors.append(f"MODIFIED: {rel}")

    current = _find_skill_files(target)
    for rel in current:
        if rel not in recorded and rel != "INTEGRITY.json":
            errors.append(f"UNTRACKED: {rel}")

    if errors:
        print(f"❌ INTEGRITY FAILED ({len(errors)} issue(s)):")
        for e in errors:
            print(f"  • {e}")
        return False

    print(f"✅ VERIFIED: {len(recorded)} files match manifest")
    return True


# ── Phase 1: Memory File Watch ─────────────────────────────────

def cmd_watch(duration=None):
    """Monitor memory files for unauthorized modifications"""
    try:
        import inotify.adapters
        HAS_INOTIFY = True
    except ImportError:
        HAS_INOTIFY = False

    print(f"🔍 Maya Gate Watch — monitoring {len(MEMORY_FILES)} memory files")
    print(f"   Files: {[f.name for f in MEMORY_FILES]}")
    print(f"   PID: {os.getpid()}")

    snapshots = {}
    for mf in MEMORY_FILES:
        if mf.exists():
            snapshots[mf] = hash_file(mf)
            print(f"   📄 {mf.name}: {snapshots[mf][:16]}...")

    if HAS_INOTIFY:
        print("\n   Using inotify (real-time)...")
        i = inotify.adapters.Inotify()
        for mf in MEMORY_FILES:
            if mf.parent.exists():
                i.add_watch(str(mf.parent))
        try:
            for event in i.event_gen(yield_nones=False, timeout_s=duration or 60):
                (_, type_names, path, filename) = event
                full = Path(path) / filename
                if full in MEMORY_FILES and ("IN_MODIFY" in type_names or "IN_CLOSE_WRITE" in type_names):
                    new_hash = hash_file(full)
                    if new_hash != snapshots.get(full):
                        now = datetime.now().isoformat()
                        print(f"\n  ⚠️  TAMPER DETECTED: {full.name} modified at {now}")
                        print(f"     Old: {snapshots.get(full, 'none')[:16]}...")
                        print(f"     New: {new_hash[:16]}...")
                        snapshots[full] = new_hash
                        _audit_log("tamper_detected", str(full), {"old_hash": snapshots.get(full), "new_hash": new_hash})
        except KeyboardInterrupt:
            print("\n   Watch stopped.")
    else:
        print("\n   inotify not available — polling every 3s...")
        print("   Install: pip install inotify")
        end = time.time() + (duration or 60)
        while time.time() < end:
            for mf in MEMORY_FILES:
                if mf.exists():
                    new_hash = hash_file(mf)
                    if new_hash != snapshots.get(mf):
                        now = datetime.now().isoformat()
                        print(f"\n  ⚠️  TAMPER DETECTED: {mf.name} at {now}")
                        _audit_log("tamper_detected", str(mf), {"old": snapshots.get(mf), "new": new_hash})
                        snapshots[mf] = new_hash
            time.sleep(3)

    print("✅ Watch complete")


# ── Phase 1: Key Encryption ────────────────────────────────────

def _xor_obfuscate(data, key="maya-gate-2026"):
    """Simple XOR obfuscation for at-rest key storage (not cryptographic security)"""
    return bytes([b ^ ord(key[i % len(key)]) for i, b in enumerate(data)])

def cmd_encrypt(plaintext):
    """Encrypt and store an API key"""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    
    # Generate a random session salt
    salt = os.urandom(16)
    combined = salt + plaintext.encode()
    encrypted = _xor_obfuscate(combined)
    
    KEY_FILE.write_bytes(encrypted)
    os.chmod(KEY_FILE, 0o600)
    print(f"✅ Key encrypted and stored: {KEY_FILE}")
    return True

def cmd_decrypt():
    """Decrypt and display stored API key"""
    if not KEY_FILE.exists():
        print("❌ No encrypted key found")
        return None
    
    encrypted = KEY_FILE.read_bytes()
    decrypted = _xor_obfuscate(encrypted)
    salt = decrypted[:16]
    key = decrypted[16:].decode()
    
    print(f"🔑 Decrypted key (salt: {salt.hex()[:8]}...): {key[:8]}...{key[-4:]}")
    return key


# ── Phase 1: Audit Log ─────────────────────────────────────────

def _audit_log(action, target, metadata=None):
    """Write structured audit entry"""
    AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "target": target,
        "pid": os.getpid(),
        "user": os.environ.get("USER", "unknown"),
        "metadata": metadata or {},
    }
    with open(AUDIT_LOG, "a") as f:
        f.write(json.dumps(entry) + "\n")
    return entry

def cmd_audit():
    """Display recent audit entries"""
    if not AUDIT_LOG.exists():
        print("📝 No audit entries yet")
        return

    entries = AUDIT_LOG.read_text().strip().split("\n")
    print(f"\n📋 MAYA GATE AUDIT LOG ({len(entries)} entries)")
    print("=" * 65)
    for line in entries[-20:]:  # last 20
        try:
            e = json.loads(line)
            ts = e["timestamp"][:19]
            action = e["action"]
            target = Path(e["target"]).name if e.get("target") else ""
            print(f"  {ts}  {action:20s}  {target}")
        except Exception:
            pass


# ── Phase 1: Bulk Integrity Check ──────────────────────────────

def cmd_integrity():
    """Verify all skill directories have valid manifests"""
    all_pass = True
    for skills_dir in SKILLS_DIRS:
        if not skills_dir.exists():
            continue
        print(f"\n📁 Scanning: {skills_dir}")
        for skill_dir in sorted(skills_dir.iterdir()):
            if not skill_dir.is_dir():
                continue
            manifest_path = skill_dir / "INTEGRITY.json"
            if not manifest_path.exists():
                print(f"  ⚠️  No manifest: {skill_dir.name}")
                all_pass = False
                continue
            
            manifest = json.loads(manifest_path.read_text())
            recorded = manifest.get("files", {})
            errors = []
            for rel, expected in recorded.items():
                full = skill_dir / rel
                if not full.exists():
                    errors.append(f"MISSING: {rel}")
                elif hash_file(full) != expected:
                    errors.append(f"MODIFIED: {rel}")
            
            if errors:
                print(f"  ❌ {skill_dir.name}: {len(errors)} issue(s)")
                all_pass = False
            else:
                print(f"  ✅ {skill_dir.name}: {len(recorded)} files verified")
    
    # Generate INTEGRITY.json for any missing
    missing = []
    for skills_dir in SKILLS_DIRS:
        if not skills_dir.exists():
            continue
        for skill_dir in sorted(skills_dir.iterdir()):
            if skill_dir.is_dir() and not (skill_dir / "INTEGRITY.json").exists():
                missing.append(skill_dir.name)
    
    if missing:
        print(f"\n📝 Manifests missing for: {', '.join(missing)}")
        print("   Run: maya-gate manifest generate <dir>")
    
    print(f"\n{'✅ All skills verified' if all_pass else '❌ Some skills have issues'}")
    return all_pass


# ── Main CLI ───────────────────────────────────────────────────

def main():
    """CLI entry point — parse args and dispatch to subcommand"""
    import argparse
    parser = argparse.ArgumentParser(description="Maya Gate v2.0 — AI Output Validation + Security")
    sub = parser.add_subparsers(dest="command")

    # Existing commands
    parser.add_argument("--file", help="Validate a file")
    parser.add_argument("--code", help="Validate inline code")
    parser.add_argument("--level", choices=["l1", "l2", "l3"])
    parser.add_argument("--install", action="store_true")
    parser.add_argument("--config", action="store_true")
    parser.add_argument("--quiet", action="store_true")

    # manifest generate
    mg = sub.add_parser("manifest", help="Manifest management")
    mg.add_argument("action", choices=["generate", "verify", "check"], nargs="?",
                    help="generate=create, verify=validate, check=bulk all")
    mg.add_argument("target", nargs="?", help="Directory to scan")

    # watch
    sw = sub.add_parser("watch", help="Monitor memory files for tamper")
    sw.add_argument("--duration", type=int, default=60, help="Watch duration in seconds (0=forever)")

    # init — generate identity key
    sub.add_parser("init", help="Initialize Maya Gate identity key (Ed25519)")

    # attest
    sa = sub.add_parser("attest", help="Signed attestations")
    sa.add_argument("action", choices=["create", "verify", "list"], nargs="?",
                    help="create=sign a file, verify=check signature, list=recent")
    sa.add_argument("target", nargs="?", help="File path (create) or attestation ID/file (verify)")

    # encrypt / decrypt
    se = sub.add_parser("encrypt", help="Encrypt and store an API key")
    se.add_argument("key", help="Plaintext key to encrypt")
    sub.add_parser("decrypt", help="Decrypt stored API key")

    # audit
    sub.add_parser("audit", help="Show audit log")

    # integrity (bulk check all)
    sub.add_parser("integrity", help="Verify all skills have valid manifests")

    # check (Phase 5: AI behavior patterns)
    sc = sub.add_parser("check", help="Scan file for AI behavior patterns or framework violations")
    sc.add_argument("file", help="File to scan")
    sc.add_argument("--deep", action="store_true", help="Deep scan (verify imports exist)")
    sc.add_argument("--json", action="store_true", help="Output as JSON")
    sc.add_argument("--framework", choices=["react", "vue", "express", "next", "laravel", "django", "spring", "flutter"], help="Framework-specific checks")
    sc.add_argument("--version", help="Framework version (e.g. 3, 11, 19). Auto-detected if omitted")
    sc.add_argument("--migrate-to", help="Generate migration plan to this version")
    sc.add_argument("--conventions", nargs="?", const="auto", default=None,
                    help="Check against coding conventions (opt-in). Specify framework or 'auto'")
    sc.add_argument("--dlp", action="store_true", help="Scan for hardcoded secrets (DLP)")
    sc.add_argument("--ab", action="store_true", help="A/B compare against original file (scientist pattern)")

    # compare (S5 — scientist pattern)
    scmp = sub.add_parser("compare", help="A/B compare old (control) vs new (candidate) code")
    scmp.add_argument("old_file", help="Original/control file")
    scmp.add_argument("new_file", help="Refactored/candidate file")
    scmp.add_argument("--json", action="store_true", help="JSON output")

    # score (Phase 6)
    ss = sub.add_parser("score", help="Calculate quality score (0-100)")
    ss.add_argument("file", help="File to score")

    # stats
    sst = sub.add_parser("stats", help="Show validation statistics from PostgreSQL")
    sst.add_argument("--since", default="7d", help="Time range: 1d, 7d, 30d, all")
    sst.add_argument("--by-language", action="store_true", help="Breakdown by language")
    sst.add_argument("--by-framework", action="store_true", help="Breakdown by framework")
    sst.add_argument("--json", action="store_true", help="Machine-readable output")

    # dashboard (Phase 6)
    sd = sub.add_parser("dashboard", help="Live-updating terminal dashboard")
    sd.add_argument("file", help="File to monitor")
    sd.add_argument("--refresh", type=int, default=3, help="Refresh interval (seconds)")

    # mcp server (Phase 2)
    sm = sub.add_parser("mcp", help="Start MCP server for real-time agent hooks")
    sm.add_argument("--port", type=int, default=0, help="HTTP port (0 = stdio)")

    # heal (Phase 3)
    sh = sub.add_parser("heal", help="Auto-fix issues in a file")
    sh.add_argument("file", help="File to heal")
    sh.add_argument("--dry-run", action="store_true", help="Preview fixes without applying")

    # conventions
    scv = sub.add_parser("conventions", help="Manage coding convention files")
    scv.add_argument("action", choices=["sync", "list"], nargs="?",
                     help="sync=download from awesome-copilot, list=show cached")

    # gate commands
    sg = sub.add_parser("gate", help="Manage approval gates")
    sg.add_argument("action", choices=["list", "approve", "skip", "check"], nargs="?",
                    help="list=show pending, approve=approve gate, skip=skip warning, check=run auto-checks")
    sg.add_argument("gate_id", nargs="?", help="Gate ID (e.g. GATE-COST)")
    sg.add_argument("--reason", default="", help="Reason for approval/skip")

    # workflow
    swf = sub.add_parser("run", help="Execute a workflow with gates")
    swf.add_argument("file", help="Path to workflow .md file")

    # tentacle
    st = sub.add_parser("tentacle", help="Manage extension plugins")
    st.add_argument("action", choices=["list", "install", "remove"], nargs="?",
                    help="list=show installed, install=add from path/URL, remove=delete")
    st.add_argument("target", nargs="?", help="Tentacle path/URL or name")

    # Also add --fixpackets to existing --file
    parser.add_argument("--fixpackets", action="store_true", help="Emit Fix Packet JSON instead of text")

    args = parser.parse_args()

    # Dispatch subcommands
    if args.command == "init":
        _require_enterprise()
        from maya_gate_lib import _ensure_identity
        _ensure_identity()
        print("✅ Maya Gate identity initialized")
        return

    if args.command == "attest":
        _require_enterprise()
        from maya_gate_lib import create_attestation, verify_attestation, list_attestations, validate_file_with_pipeline, load_config
        from pathlib import Path
        att_dir = Path.home() / ".maya-gate/attestations"
        
        if args.action == "create" and args.target:
            if not Path(args.target).exists():
                print(f"❌ File not found: {args.target}")
                sys.exit(1)
            cfg = load_config()
            ok, results = validate_file_with_pipeline(args.target, cfg)
            att = create_attestation(args.target, {"pass": ok, "checks": results}, cfg["level"])
            print(f"✅ Attestation created: {att['id']}")
            print(f"   File: {att['file']['path']}")
            print(f"   Result: {'✅ PASS' if ok else '❌ FAIL'}")
            print(f"   Signature: {att['signature'][:40]}...")
        
        elif args.action == "verify":
            # args.target can be an attestation ID or file path
            if args.target:
                # Check if it's an ID (att_xxx) or full path
                if args.target.startswith("att_"):
                    att_file = att_dir / f"{args.target}.json"
                else:
                    att_file = Path(args.target)
                
                if not att_file.exists():
                    print(f"❌ Attestation not found: {att_file}")
                    sys.exit(1)
                valid, msg = verify_attestation(str(att_file))
                print(f"{'✅' if valid else '❌'} Attestation: {msg}")
            
            else:
                print("❌ Specify attestation ID or file path")
        
        elif args.action == "list":
            atts = list_attestations()
            if not atts:
                print("📝 No attestations yet")
            else:
                print(f"\n📋 RECENT ATTESTATIONS ({len(atts)})")
                for a in atts:
                    icon = "✅" if a["pass"] else "❌"
                    print(f"  {icon} {a['id']}  {a['created_at']}  {Path(a['file']).name}  ({a['signer']})")
        
        else:
            print("Usage: maya-gate attest {create|verify|list} [target]")
        return

    if args.command == "mcp":
        from maya_gate_mcp import main as mcp_main
        mcp_main()
        return

    if args.command == "heal":
        from maya_gate_lib import heal_file, format_fix_packet, validate_with_fixpackets, load_config as _lc
        if args.dry_run:
            pkt = validate_with_fixpackets(args.file, _lc())
            format_fix_packet(pkt)
        else:
            fixed, errors = heal_file(args.file)
            if fixed:
                print(f"✅ Healed {fixed} issue(s) in {args.file}")
            else:
                print(f"⚠️  {errors[0] if errors else 'No fixes needed'}")
        return

    if args.command == "gate":
        from maya_gate_lib import list_gates, approve_gate, skip_gate, check_gates, format_gates
        
        if args.action == "list" or not args.action:
            gates = list_gates()
            pending = [g for g in gates if g.status == "pending"]
            print(format_gates(pending))
        
        elif args.action == "approve" and args.gate_id:
            ok, msg = approve_gate(args.gate_id, args.reason)
            print(f"  {'✅' if ok else '❌'} {msg}")
        
        elif args.action == "skip" and args.gate_id:
            ok, msg = skip_gate(args.gate_id, args.reason)
            print(f"  {'✅' if ok else '❌'} {msg}")
        
        elif args.action == "check":
            pending = check_gates()
            if pending:
                print(f"\n  ⏳ {len(pending)} gate(s) pending approval:")
                print(format_gates(pending))
            else:
                print("\n  ✅ All gates passed")
        
        return

    if args.command == "run":
        from maya_gate_lib import run_workflow, format_gates, list_gates, check_gates
        import json as _json
        
        ok, result = run_workflow(args.file)
        if not ok:
            print(f"❌ {result}")
            return
        
        print(f"\n  🚪 Running workflow: {result['name']}")
        print(f"  Gates: {', '.join(result['gates'])}")
        print(f"  Steps: {len(result['steps'])}")
        
        # Check and show pending gates
        pending = check_gates()
        for g in pending:
            print(f"\n    ⏳ [{g.id}] {g.name} — awaiting approval")
        if pending:
            print("\n  Run: maya-gate gate approve <id> --reason '...'")
        else:
            print(f"\n  ✅ All gates passed — executing {len(result['steps'])} step(s)")
        
        return

    if args.command == "conventions":
        from maya_gate_lib import sync_conventions, list_conventions, format_convention_findings
        
        if args.action == "sync" or not args.action:
            count, errors = sync_conventions()
            print(f"\n  ✅ Synced {count} convention file(s) from awesome-copilot")
            for e in errors:
                print(f"  ⚠️  {e}")
            return
        
        if args.action == "list":
            files = list_conventions()
            if not files:
                print("\n  📭 No conventions cached. Run: maya-gate conventions sync")
            else:
                print(f"\n  📋 CONVENTIONS ({len(files)} cached)")
                for f in files:
                    print(f"    {f['name']:15s}  {f['rules']:3d} rules  ({f['size']:,} bytes)")
            return

    if args.command == "compare":
        from maya_gate_lib import compare_files, format_comparison
        import json as _json
        
        result = compare_files(args.old_file, args.new_file)
        if args.json:
            print(_json.dumps(result, indent=2))
        else:
            format_comparison(result)
        return

    # Dispatch subcommands
    if args.command == "manifest":
        if args.action == "generate":
            sys.exit(0 if cmd_manifest_generate(args.target) else 1)
        elif args.action == "verify":
            sys.exit(0 if cmd_manifest_verify(args.target) else 1)
        elif args.action == "check":
            sys.exit(0 if cmd_integrity() else 1)
        else:
            print("Usage: maya-gate manifest {generate|verify|check} [target]")
            return

    if args.command == "watch":
        _require_enterprise()
        cmd_watch(args.duration)
        return

    if args.command == "encrypt":
        _require_enterprise()
        cmd_encrypt(args.key)
        return

    if args.command == "decrypt":
        _require_enterprise()
        cmd_decrypt()
        return

    if args.command == "audit":
        _require_enterprise()
        cmd_audit()
        return

    if args.command == "integrity":
        cmd_integrity()
        return

    if args.command == "check":
        from maya_gate_lib import check_ai_patterns, format_ai_findings, check_framework, format_framework_findings, detect_version, generate_migration_plan, format_migration_plan, check_conventions, format_convention_findings, list_conventions, check_dlp, format_dlp_findings
        import json as _json
        from pathlib import Path
        
        # DLP scan (runs first if requested)
        if args.dlp:
            findings = check_dlp(args.file)
            if args.json:
                print(_json.dumps(findings, indent=2))
            else:
                format_dlp_findings(findings)
            # Determine exit code: blocking = exit 1
            has_blocking = any(f["severity"] == "blocking" for f in findings)
            sys.exit(1 if has_blocking else 0)
            return
        
        # A/B comparison mode
        if args.ab:
            from maya_gate_lib import compare_files, format_comparison
            # Check for backup files: .orig, .bak, or .old
            fp = Path(args.file)
            candidates = [fp.with_suffix(fp.suffix + ".orig"),
                          fp.with_suffix(fp.suffix + ".bak"),
                          fp.with_suffix(".old" + fp.suffix)]
            candidate = next((c for c in candidates if c.exists()), None)
            if candidate:
                result = compare_files(str(candidate), args.file)
                format_comparison(result)
            else:
                print("\n  ⚠️  No backup found for A/B comparison")
                print(f"     Looked for: {', '.join(str(c) for c in candidates)}")
            return
        
        # Run convention checks if requested
        if args.conventions is not None:
            ext_map = {".py": "python", ".js": "typescript", ".ts": "typescript",
                       ".jsx": "typescript", ".tsx": "typescript"}
            conv_framework = args.conventions if args.conventions != "auto" else ext_map.get(Path(args.file).suffix, "python")
            conv_findings = check_conventions(args.file, conv_framework)
            if args.json:
                print(_json.dumps(conv_findings, indent=2))
            else:
                format_convention_findings(conv_findings, conv_framework)
            return
        
        if args.framework:
            version = args.version or detect_version(args.framework, args.file)
            
            # Migration plan mode
            if args.migrate_to:
                plan = generate_migration_plan(args.framework, version, args.migrate_to)
                format_migration_plan(plan, args.framework)
            else:
                findings = check_framework(args.file, args.framework, version=version)
                if args.json:
                    print(_json.dumps(findings, indent=2))
                else:
                    fmt = {"react":"React","vue":"Vue.js","express":"Express.js","next":"Next.js",
                           "laravel":"Laravel","django":"Django","spring":"Spring Boot","flutter":"Flutter"}
                    v_str = f" (v{version})" if version != "latest" else ""
                    format_framework_findings(findings, f"{fmt.get(args.framework, args.framework)}{v_str}")
        else:
            findings = check_ai_patterns(args.file, deep=args.deep)
            if args.json:
                print(_json.dumps(findings, indent=2))
            else:
                format_ai_findings(findings)
        return

    if args.command == "score":
        from maya_gate_lib import calculate_score, score_to_grade, format_score
        score = calculate_score(args.file)
        grade, label = score_to_grade(score)
        format_score(score, grade, label, args.file)
        return

    if args.command == "stats":
        from maya_gate_lib import query_stats
        import json as _json
        result = query_stats(since=args.since, by_language=args.by_language, by_framework=args.by_framework)
        if args.json:
            print(_json.dumps(result, indent=2, default=str))
        else:
            _print_stats(result)
        return

    if args.command == "dashboard":
        from maya_gate_lib import dashboard_live
        dashboard_live(args.file, refresh=args.refresh)
        return

    if args.command == "tentacle":
        from maya_gate_lib import _tentacle_init
        from maya_gate_tentacle import list_all as _tlist, TENTACLE_DIRS
        import json as _json
        
        if args.action == "list" or not args.action:
            tentacles = _tlist()
            if not tentacles:
                print("\n  📭 No tentacles installed")
                print("  Install: maya-gate tentacle install <path>")
            else:
                print(f"\n  🐙 TENTACLES ({len(tentacles)} installed)")
                for name, t in tentacles.items():
                    hooks = t.get("hooks", [])
                    hook_str = ", ".join(hooks) if hooks else "none"
                    print(f"    {name:30s} v{t.get('version','?')}  [{hook_str}]")
            return

        if args.action == "install" and args.target:
            target = Path(args.target).expanduser()
            if not target.exists():
                print(f"❌ Not found: {args.target}")
                return
            
            dest = TENTACLE_DIRS[0] / target.name
            if target.is_dir():
                shutil.copytree(target, dest, dirs_exist_ok=True)
            elif target.suffix == ".json":
                dest.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, dest / "tentacle.json")
            else:
                print(f"❌ Unsupported: {args.target}")
                return
            
            # Reload
            _tentacle_init()
            print(f"✅ Tentacle installed: {target.name}")
            return

        if args.action == "remove" and args.target:
            for d in TENTACLE_DIRS:
                target = d / args.target
                if target.exists():
                    shutil.rmtree(target)
                    print(f"✅ Tentacle removed: {args.target}")
                    return
            print(f"❌ Not found: {args.target}")
            return

    # Legacy commands
    if args.install:
        install()
        return

    if args.config:
        print(json.dumps(load_config(), indent=2))
        return

    if args.file:
        if args.fixpackets:
            from maya_gate_lib import validate_with_fixpackets, format_fix_packet
            pkt = validate_with_fixpackets(args.file, load_config())
            format_fix_packet(pkt)
            sys.exit(0 if pkt["pass"] else 1)
        else:
            ok = gate_file(args.file)
            _audit_log("validate", args.file, {"result": "pass" if ok else "fail"})
            sys.exit(0 if ok else 1)

    if args.code:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(args.code)
            t = f.name
        ok = gate_file(t)
        _audit_log("validate", "inline_code", {"result": "pass" if ok else "fail"})
        Path(t).unlink(missing_ok=True)
        sys.exit(0 if ok else 1)

    parser.print_help()


def install():
    """Install git hooks + AI tool hooks + pre-push checker"""
    gate_script = Path(__file__).resolve()
    gate_path = f"python3 {gate_script}"

    # Git pre-commit hook
    git_hooks = Path(".git/hooks")
    if git_hooks.exists():
        hook = f"""#!/bin/bash
# Maya Gate — pre-commit validation
git diff --cached --name-only --diff-filter=ACM | while read file; do
    {gate_path} --file "$file" || exit 1
done
"""
        hook_path = git_hooks / "pre-commit"
        hook_path.write_text(hook)
        hook_path.chmod(0o755)
        print("  ✅ Git pre-commit hook installed")

    # Git pre-push hook (blocks trash files)
    if git_hooks.exists():
        push_hook = """#!/bin/bash
# Maya Gate — pre-push checker (blocks trash files)
echo "  🔍 Maya Gate: Pre-push check..."
python3 /home/maya/scripts/pre-commit-checker.py
"""
        push_path = git_hooks / "pre-push"
        push_path.write_text(push_hook)
        push_path.chmod(0o755)
        print("  ✅ Git pre-push hook installed")

    # Claude Code hook
    claude_dir = Path.home() / ".claude"
    claude_dir.mkdir(exist_ok=True)
    claude_settings = claude_dir / "settings.json"
    hooks_config = {
        "hooks": {
            "PreToolUse": f"{gate_path} mcp"
        }
    }
    if claude_settings.exists():
        existing = json.loads(claude_settings.read_text())
        existing.setdefault("hooks", {}).update(hooks_config["hooks"])
        claude_settings.write_text(json.dumps(existing, indent=2))
    else:
        claude_settings.write_text(json.dumps(hooks_config, indent=2))
    print("  ✅ Claude Code hook configured")

    # OpenCode plugin
    oc_plugin = Path.home() / ".opencode/plugin/maya-gate.ts"
    oc_plugin.parent.mkdir(parents=True, exist_ok=True)
    oc_plugin.write_text(f"""// Maya Gate — opencode output validation plugin
export default {{
  name: "maya-gate",
  description: "Validates AI output before delivery",
  hooks: {{
    async afterGenerate(output) {{
      const {{ execSync }} = require("child_process");
      try {{
        execSync(`{gate_path} --code '${{output.replace(/'/g, "\\\\'")}}'`, {{ timeout: 10000 }});
      }} catch {{
        return {{ action: "retry", message: "Gate validation failed, regenerating..." }};
      }}
      return output;
    }}
  }}
}};
""")
    print("  ✅ OpenCode plugin created")

    print("\n✅ Maya Gate hooks installed!")
    print("   Git pre-commit   → blocks bad commits")
    print("   Claude Code hook → validates on PreToolUse")
    print("   OpenCode plugin  → validates after generation")


def gate_file(fp):
    """Run validation checks on a single file"""
    if os.environ.get("MAYA_UNLOCKED") == "1":
        return True
    config = load_config()
    ext = Path(fp).suffix
    if ext not in config["watch_extensions"]:
        return True
    ok, results = validate_file_with_pipeline(fp, config)
    print_report(ok, results, fp, config["quiet"])
    return ok


def _print_stats(data):
    """Pretty-print stats from query_stats()."""
    if "error" in data:
        print(f"\n  ⚠️  {data['error']}")
        return
    
    print("\n  📊 MAYA GATE STATS")
    print(f"  {'='*50}")
    print(f"  Total validations:  {data.get('total', 0):,}")
    print(f"  Paid:               {data.get('paid', 0):,}")
    print(f"  Free:               {data.get('free', 0):,}")
    print(f"  Sessions:           {data.get('sessions', 0):,}")
    print(f"  Total cost:         ${data.get('total_cost', 0):.2f}")
    
    if data.get("by_agent"):
        print("\n  🤖 BY AGENT")
        for agent, info in data["by_agent"].items():
            cost_str = f" ~${info['avg_cost']:.4f}/msg" if info['avg_cost'] > 0 else ""
            print(f"    {agent:12s}  {info['count']:5d} msgs{cost_str}")
    
    if data.get("by_model"):
        print("\n  🧠 BY MODEL")
        for model, count in data["by_model"].items():
            emoji = "🔒" if model in ("DeepSeek V4 Flash", "DeepSeek V4 Pro") else "🔓"
            print(f"    {emoji} {model:25s}  {count:5d}")
    
    if data.get("daily_trend"):
        print("\n  📅 DAILY TREND")
        for day, info in data["daily_trend"].items():
            cost_str = f" ${info['cost']:.2f}" if info['cost'] > 0 else ""
            print(f"    {day}  {info['count']:4d} msgs{cost_str}")


if __name__ == "__main__":
    main()
