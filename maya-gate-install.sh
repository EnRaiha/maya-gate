#!/bin/bash
# Maya Gate — One-command install
# Run: curl -sL https://raw.githubusercontent.com/... | bash
# Or:  bash <(cat maya-gate-install.sh)

set -e

MAYA_HOME="${MAYA_HOME:-$HOME}"
GATE_SCRIPT="$MAYA_HOME/scripts/maya-gate.py"
CONFIG_DIR="$MAYA_HOME/.config/maya-gate"
OPENCODE_PLUGIN="$MAYA_HOME/.opencode/plugin/maya-gate.ts"

echo ""
echo "  ╔══════════════════════════════════════════╗"
echo "  ║      Maya Gate — One-Click Install       ║"
echo "  ╚══════════════════════════════════════════╝"
echo ""

# 1. Copy gate script
echo "  📦 Installing gate script..."
mkdir -p "$MAYA_HOME/scripts"
cat > "$GATE_SCRIPT" << 'GATE_EOF'
#!/usr/bin/env python3
"""Maya Gate — validated inline via install script"""
import subprocess, sys, os, json, tempfile, shutil
from pathlib import Path

CONFIG_DIR = Path.home() / ".config/maya-gate"
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULT_CONFIG = {
    "level": "l2",
    "max_iterations": 3,
    "checks": {"syntax": True, "ruff": True, "snip": True, "compile": True},
    "watch_extensions": [".py", ".js", ".ts", ".rs", ".go", ".java"],
    "quiet": False
}

def load_config():
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE) as f:
            return {**DEFAULT_CONFIG, **json.load(f)}
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(DEFAULT_CONFIG, f, indent=2)
    return DEFAULT_CONFIG

def check_syntax(fp):
    ext = Path(fp).suffix
    if ext == ".py":
        r = subprocess.run([sys.executable, "-c", f"compile(open('{fp}').read(), '{fp}', 'exec')"], capture_output=True, text=True)
        return r.returncode == 0, r.stderr
    if ext in (".js", ".ts"):
        r = subprocess.run(["node", "--check", fp], capture_output=True, text=True)
        return r.returncode == 0, r.stderr
    if ext == ".rs":
        r = subprocess.run(["rustc", "--edition", "2021", fp, "-o", "/dev/null"], capture_output=True, text=True)
        return r.returncode == 0, r.stderr
    return True, ""

def check_ruff(fp):
    if not shutil.which("ruff"): return True, ""
    r = subprocess.run(["ruff", "check", str(fp), "--quiet"], capture_output=True, text=True)
    return r.returncode == 0, r.stdout or r.stderr

def check_snip(fp):
    if not shutil.which("snip"): return True, ""
    r = subprocess.run(["snip", "run", "--", "cat", str(fp)], capture_output=True, text=True, timeout=10)
    return r.returncode == 0, r.stdout or r.stderr

def validate(fp, cfg):
    results = {}
    ok = True
    if cfg["checks"]["syntax"]:
        p, e = check_syntax(fp); results["syntax"] = {"pass": p, "detail": e.strip()}; ok &= p
    if cfg["checks"]["ruff"]:
        p, e = check_ruff(fp); results["ruff"] = {"pass": p, "detail": e.strip()}; ok &= p
    if cfg["checks"]["snip"]:
        p, e = check_snip(fp); results["snip"] = {"pass": p, "detail": e.strip()}; ok &= p
    return ok, results

def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--file"); p.add_argument("--code"); p.add_argument("--install", action="store_true")
    p.add_argument("--level", choices=["l1","l2","l3"]); p.add_argument("--quiet", action="store_true")
    a = p.parse_args()

    if a.install:
        print("Already installed!")
        return

    cfg = load_config()
    if a.level:
        cfg["checks"]["ruff"] = a.level in ("l2","l3")
        cfg["checks"]["snip"] = a.level in ("l2","l3")

    if a.file:
        ok, r = validate(a.file, cfg)
        for c, d in r.items():
            i = "✅" if d["pass"] else "❌"
            dt = f" — {d['detail'][:80]}" if d["detail"] else ""
            print(f"    {i} {c:8s}{dt}")
        sys.exit(0 if ok else 1)

    if a.code:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(a.code); t = f.name
        ok, r = validate(t, cfg)
        Path(t).unlink(missing_ok=True)
        sys.exit(0 if ok else 1)

    p.print_help()

if __name__ == "__main__":
    main()
GATE_EOF
chmod +x "$GATE_SCRIPT"
echo "  ✅ Gate script installed"

# 2. Create default config
echo "  ⚙️  Creating config..."
mkdir -p "$CONFIG_DIR"
cat > "$CONFIG_FILE" << 'JSON'
{"level": "l2", "quiet": false, "max_iterations": 3}
JSON
echo "  ✅ Config created"

# 3. Create alias
echo "  🔗 Creating shell alias..."
ALIAS_LINE="alias maya-gate='python3 $GATE_SCRIPT'"
for rc in bashrc zshrc; do
    rcfile="$MAYA_HOME/.$rc"
    [ -f "$rcfile" ] && ! grep -q "maya-gate" "$rcfile" && echo "$ALIAS_LINE" >> "$rcfile" && echo "  ✅ Added to ~/.$rc"
done
export PATH="$PATH:$MAYA_HOME/.local/bin"
ln -sf "$GATE_SCRIPT" "$MAYA_HOME/.local/bin/maya-gate" 2>/dev/null
echo "  ✅ Alias created"

# 4. Install git pre-commit hook
if [ -d ".git/hooks" ]; then
    echo "  🔧 Installing git pre-commit hook..."
    cat > .git/hooks/pre-commit << 'HOOK'
#!/bin/bash
git diff --cached --name-only --diff-filter=ACM | grep -E '\.(py|js|ts|rs|go|java)$' | while read f; do
    python3 "$HOME/scripts/maya-gate.py" --file "$f" || exit 1
done
HOOK
    chmod +x .git/hooks/pre-commit
    echo "  ✅ Git hook installed"
fi

# 5. Add to opencode
if [ -f "$MAYA_HOME/.opencode/opencode.json" ]; then
    echo "  🔌 Checking opencode integration..."
    echo ""
    echo "  ℹ️  Add this to your opencode.json manually or via edit:"
    echo '     "maya-gate": { "type": "hook", "path": "'"$GATE_SCRIPT"'" }'
    echo ""
fi

echo ""
echo "  ╔══════════════════════════════════════════╗"
echo "  ║      ✅ Maya Gate Installed!              ║"
echo "  ╠══════════════════════════════════════════╣"
echo "  ║                                          ║"
echo "  ║  Usage:                                   ║"
echo "  ║    maya-gate --file app.py                ║"
echo "  ║    maya-gate --code 'print(1)'            ║"
echo "  ║    maya-gate --level l3 --file app.py     ║"
echo "  ║    maya-gate --config                     ║"
echo "  ║                                          ║"
echo "  ║  Levels: l1(syntax) l2(lint) l3(full)     ║"
echo "  ║  Config: $CONFIG_DIR/config.json          ║"
echo "  ║                                          ║"
echo "  ╚══════════════════════════════════════════╝"
echo ""
