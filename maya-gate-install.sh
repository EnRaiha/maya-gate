#!/bin/bash
# Maya Gate — One-command install
# Run: curl -sL https://raw.githubusercontent.com/... | bash
# Or:  bash <(cat maya-gate-install.sh)

set -e

MAYA_HOME="${MAYA_HOME:-$HOME}"
GATE_SCRIPT="$MAYA_HOME/scripts/maya-gate.py"
GATE_LIB="$MAYA_HOME/scripts/maya_gate_lib.py"
CONFIG_DIR="$MAYA_HOME/.config/maya-gate"
OPENCODE_PLUGIN="$MAYA_HOME/.opencode/plugin/maya-gate.ts"
GATE_REPO="https://raw.githubusercontent.com/EnRaiha/maya-gate/main"

echo ""
echo "  ╔══════════════════════════════════════════╗"
echo "  ║      Maya Gate — One-Click Install       ║"
echo "  ╚══════════════════════════════════════════╝"
echo ""

# 1. Download gate script + lib
echo "  📦 Downloading Maya Gate from GitHub..."
mkdir -p "$MAYA_HOME/scripts"
if command -v curl &>/dev/null; then
    curl -sL "$GATE_REPO/maya-gate.py" -o "$GATE_SCRIPT"
    curl -sL "$GATE_REPO/maya_gate_lib.py" -o "$GATE_LIB"
elif command -v wget &>/dev/null; then
    wget -q "$GATE_REPO/maya-gate.py" -O "$GATE_SCRIPT"
    wget -q "$GATE_REPO/maya_gate_lib.py" -O "$GATE_LIB"
else
    echo "  ❌ curl or wget required. Install one and retry."
    exit 1
fi
chmod +x "$GATE_SCRIPT"
echo "  ✅ Maya Gate downloaded ($(wc -l < "$GATE_SCRIPT") lines)"

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
echo "  ║    maya-gate --pipeline --file app.py     ║"
echo "  ║                                          ║"
echo "  ║  Levels: l1(syntax) l2(lint) l3(full)     ║"
echo "  ║  Pipeline: DLP + convention checks run     ║"
echo "  ║           automatically at l3              ║"
echo "  ║  Config: $CONFIG_DIR/config.json          ║"
echo "  ║                                          ║"
echo "  ╚══════════════════════════════════════════╝"
echo ""
