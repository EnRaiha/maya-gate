#!/usr/bin/env bash
# Maya Gate Uninstall — removes hooks, keeps script files
# Reversible: run "python3 maya-gate.py install" to restore
set -euo pipefail

DRY_RUN=false
if [[ "${1:-}" == "--dry-run" ]]; then DRY_RUN=true; fi

del() { echo "  rm $1"; $DRY_RUN || rm -rf "$1"; }
pyjson() { $DRY_RUN || python3 -c "$1"; }

echo "===== Maya Gate Uninstall ====="
echo ""

# 1. Claude Code hook — remove PreToolUse if it points to maya-gate
CLAUDE_CFG="$HOME/.claude/settings.json"
if [[ -f "$CLAUDE_CFG" ]]; then
    if python3 -c "
import json, pathlib
cfg = json.loads(pathlib.Path('$CLAUDE_CFG').read_text())
ptu = cfg.get('hooks', {}).get('PreToolUse', '')
print('MATCH' if 'maya-gate.py' in str(ptu) else 'NONE')
" | grep -q MATCH 2>/dev/null; then
        pyjson "
import json, pathlib
f = pathlib.Path('$CLAUDE_CFG')
cfg = json.loads(f.read_text())
del cfg['hooks']['PreToolUse']
if not cfg['hooks']: del cfg['hooks']
f.write_text(json.dumps(cfg, indent=2) + '\n')
print('✅ Claude PreToolUse hook removed')
"
    else
        echo "  ⏭  Claude hook not found or already removed"
    fi
fi

# 2. OpenCode plugin
OC_PLUGIN="$HOME/.opencode/plugin/maya-gate.ts"
if [[ -f "$OC_PLUGIN" ]]; then
    del "$OC_PLUGIN"
    echo "  ✅ OpenCode plugin removed"
else
    echo "  ⏭  OpenCode plugin not found"
fi

# 3. Git pre-commit hook (remove maya-gate lines only)
for repo in "$HOME/scripts/.git/hooks" "$HOME/Bumi-Hijau/.git/hooks"; do
    HOOK="$repo/pre-commit"
    if [[ -f "$HOOK" ]] && grep -q "maya-gate" "$HOOK" 2>/dev/null; then
        del "$HOOK"
        echo "  ✅ Git pre-commit hook removed: $HOOK"
    fi
done

# 4. Git pre-push hook
for repo in "$HOME/scripts/.git/hooks" "$HOME/Bumi-Hijau/.git/hooks"; do
    HOOK="$repo/pre-push"
    if [[ -f "$HOOK" ]] && grep -q "maya-gate" "$HOOK" 2>/dev/null; then
        del "$HOOK"
        echo "  ✅ Git pre-push hook removed: $HOOK"
    fi
done

# 5. Temp clones
del "/tmp/maya-gate"

# 6. Script files — NOT deleted (kept in ~/scripts/)
echo ""
echo "  📁 Script files kept at:"
echo "     $HOME/scripts/maya-gate.py"
echo "     $HOME/scripts/maya_gate_lib.py"
echo "     $HOME/scripts/maya_gate_tentacle.py"
echo "     $HOME/scripts/maya-gate-mcp.py"

echo ""
echo "  🔁 Reinstall: python3 ~/scripts/maya-gate.py install"
echo "===== Done ====="
