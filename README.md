# Maya Gate

AI output validation gate. Validates, scores, and secures AI-generated code — syntax checks, ruff linting, snip filtering, framework-specific audits, DLP scanning, and signed attestations.

```
maya-gate --file app.py              Validate a file
maya-gate score <file>               Quality score 0-100
maya-gate check <file>               AI behavior patterns + DLP scan
maya-gate heal <file>                Auto-fix issues
maya-gate dashboard <file>           Live terminal dashboard
maya-gate mcp                        Start MCP server
maya-gate install                    Install git/Claude/OpenCode hooks
maya-gate manifest generate|verify   Skill integrity manifests
maya-gate attest create|verify|list  Ed25519 signed attestations (enterprise)
maya-gate watch                      Memory file tamper detection (enterprise)
maya-gate encrypt|decrypt            Key management (enterprise)
maya-gate audit                      Execution history (enterprise)
maya-gate gate list|approve|skip     Approval gates
maya-gate run <workflow>             Execute workflow with gates
maya-gate tentacle list|install      Plugin management
maya-gate compare <old> <new>        A/B code comparison
maya-gate stats                      PostgreSQL validation stats
maya-gate conventions sync|list      Coding convention sync
```

## Quick Start

```bash
maya-gate --file mycode.py           # basic validation
maya-gate heal mycode.py             # auto-fix issues
maya-gate score mycode.py            # quality score
maya-gate check mycode.py --dlp      # secret scanning
```

## Install Hooks

```bash
maya-gate install
```

Installs git pre-commit, Claude Code PreToolUse hook, and OpenCode plugin.

## Framework Checks

```bash
maya-gate check app.tsx --framework react           # React patterns
maya-gate check app.tsx --framework react --migrate-to 19  # migration plan
maya-gate check app.tsx --conventions               # coding style
maya-gate check app.tsx --dlp                       # hardcoded secrets
maya-gate check app.tsx --ab                        # A/B compare with backup
```

## MCP Server

```bash
maya-gate mcp --port 9090       # HTTP mode
maya-gate mcp                    # stdio mode (Claude Code)
```

## License

MIT
