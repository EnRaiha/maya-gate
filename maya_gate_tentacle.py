"""
Maya Gate Tentacle System — Plugin framework for extensible validation.

Tentacles are self-contained plugins that add languages, frameworks,
security checks, or custom rules to Maya Gate. Anyone can write one
without forking the main repo.

Structure:
  ~/.config/maya-gate/tentacles/<name>/
      tentacle.json      ← Manifest
      check.py           ← Optional: Python checker
      *.sh               ← Optional: shell checkers

  .maya-gate/tentacles/<name>/   ← Project-level (version-controlled)
"""

import json
import subprocess
import importlib.util
import inspect
import shutil
from pathlib import Path

TENTACLE_DIRS = [
    Path.home() / ".config/maya-gate/tentacles",
]

PROJECT_TENTACLE_DIR = Path(".maya-gate/tentacles")


# ── Hook Points ────────────────────────────────────────────────

HOOK_POINTS = [
    "syntax",       # Register a new language syntax checker
    "framework",    # Framework pattern detection
    "validate",     # Custom validation (main hook)
    "pre_validate", # Transform file before validation
    "post_validate",# Modify results after validation
    "score",        # Adjust quality score
]


# ── Base Tentacle Class ────────────────────────────────────────

class BaseTentacle:
    """Base class for all tentacles. Subclass this and register hooks."""

    name: str = ""
    version: str = "1.0.0"
    description: str = ""
    author: str = ""
    hooks: list = []  # Which hook points this tentacle uses
    dependencies: dict = {}  # Required tools: {"python": "3.8+"}
    config: dict = {}  # Tentacle-specific config

    def __init__(self, manifest_path: Path | None = None):
        if manifest_path:
            self.load_manifest(manifest_path)
        self._check_dependencies()

    def load_manifest(self, path: Path):
        """Load configuration from tentacle.json."""
        data = json.loads(path.read_text())
        self.name = data.get("name", self.name)
        self.version = data.get("version", self.version)
        self.description = data.get("description", self.description)
        self.author = data.get("author", self.author)
        self.hooks = data.get("hooks", self.hooks)
        self.dependencies = data.get("dependencies", self.dependencies)
        self.config = data.get("config", self.config)

    def _check_dependencies(self):
        """Verify required tools are installed."""
        missing = []
        for tool, ver in self.dependencies.items():
            if tool == "maya-gate":
                continue  # Handled by version constraint
            if not shutil.which(tool):
                missing.append(tool)
        if missing:
            raise RuntimeError(f"Tentacle '{self.name}' missing: {', '.join(missing)}")

    # ── Hook Implementations (override these) ──────────────────

    def syntax_check(self, file_path: str) -> tuple[bool, str]:
        """Check syntax for a language this tentacle registers."""
        return True, ""

    def framework_detect(self, file_path: str) -> list[dict]:
        """Detect framework patterns in a file."""
        return []

    def validate(self, file_path: str, context: dict = None) -> list[dict]:
        """Run custom validation. Return list of findings."""
        return []

    def pre_validate(self, file_path: str, content: str) -> str:
        """Transform file content before validation."""
        return content

    def post_validate(self, file_path: str, findings: list) -> list:
        """Modify or annotate findings after validation."""
        return findings

    def score_adjustment(self, score: int) -> int:
        """Adjust quality score."""
        return score

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "author": self.author,
            "hooks": self.hooks,
            "dependencies": self.dependencies,
        }


# ── Built-in: Legacy Shell Checker Bridge ──────────────────────

class ShellCheckerTentacle(BaseTentacle):
    """Auto-wraps legacy ~/.config/maya-gate/checkers/*.sh scripts."""

    name = "legacy-checkers"
    description = "Bridges old .sh checker scripts into the tentacle system"
    hooks = ["syntax"]

    def __init__(self, checkers_dir: Path):
        self.checkers_dir = checkers_dir
        self.scripts: dict[str, Path] = {}
        if checkers_dir.exists():
            for f in checkers_dir.iterdir():
                if f.suffix == ".sh":
                    ext = f.stem  # "cs" → ".cs"
                    if not ext.startswith("."):
                        ext = f".{ext}"
                    self.scripts[ext] = f

    def syntax_check(self, file_path: str) -> tuple[bool, str]:
        ext = Path(file_path).suffix
        checker = self.scripts.get(ext)
        if not checker:
            return True, ""
        r = subprocess.run(["bash", str(checker), file_path],
                          capture_output=True, text=True, timeout=30)
        ok = r.returncode == 0
        detail = r.stderr.strip() or r.stdout.strip()
        return ok, detail[:200] if detail else ""


# ── Tentacle Registry ──────────────────────────────────────────

_registry: dict[str, BaseTentacle] = {}


def register(tentacle: BaseTentacle):
    """Register a tentacle instance."""
    if tentacle.name in _registry:
        raise ValueError(f"Tentacle '{tentacle.name}' already registered")
    _registry[tentacle.name] = tentacle


def get(name: str) -> BaseTentacle | None:
    return _registry.get(name)


def list_all() -> dict:
    return {n: t.to_dict() for n, t in _registry.items()}


# ── Discovery ──────────────────────────────────────────────────

def discover() -> dict[str, BaseTentacle]:
    """Scan all tentacle directories and load tentacles."""
    discovered = {}

    # Scan each tentacle directory
    for base_dir in TENTACLE_DIRS:
        if not base_dir.exists():
            continue
        for tentacle_dir in sorted(base_dir.iterdir()):
            if not tentacle_dir.is_dir():
                continue
            manifest = tentacle_dir / "tentacle.json"
            if not manifest.exists():
                continue

            try:
                t = _load_tentacle(tentacle_dir, manifest)
                if t and t.name:
                    discovered[t.name] = t
            except Exception as e:
                print(f"  ⚠️  Tentacle load failed: {tentacle_dir.name} — {e}")

    # Legacy checkers bridge
    checkers_dir = Path.home() / ".config/maya-gate/checkers"
    if checkers_dir.exists():
        legacy = ShellCheckerTentacle(checkers_dir)
        if legacy.scripts:
            discovered["legacy-checkers"] = legacy

    return discovered


def _load_tentacle(tentacle_dir: Path, manifest_path: Path) -> BaseTentacle | None:
    """Load a tentacle from its directory."""
    manifest = json.loads(manifest_path.read_text())
    name = manifest.get("name", tentacle_dir.name)

    # Check for Python checker
    py_checker = tentacle_dir / "check.py"
    if py_checker.exists():
        # Try dynamic import
        spec = importlib.util.spec_from_file_location(
            f"tentacle_{name}", str(py_checker)
        )
        if spec and spec.loader:
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            # Find any BaseTentacle subclass
            for obj_name in dir(mod):
                obj = getattr(mod, obj_name)
                if inspect.isclass(obj) and issubclass(obj, BaseTentacle) and obj is not BaseTentacle:
                    instance = obj(manifest_path)
                    return instance

    # Python-less tentacle: use manifest + optional shell scripts
    t = BaseTentacle(manifest_path)
    # Check for shell checkers
    for f in tentacle_dir.iterdir():
        if f.suffix == ".sh":
            t.hooks.append("syntax")
            break
    return t


# ── Hook Dispatch ──────────────────────────────────────────────

def dispatch_syntax(file_path: str) -> list[tuple[str, bool, str]]:
    """Run syntax check from all registered tentacles."""
    results = []
    for t in _registry.values():
        ok, msg = t.syntax_check(file_path)
        if not ok:
            results.append((t.name, ok, msg))
    return results


def dispatch_framework(file_path: str) -> list[dict]:
    """Run framework detection from all tentacles."""
    results = []
    for t in _registry.values():
        results.extend(t.framework_detect(file_path))
    return results


def dispatch_validate(file_path: str, context: dict = None) -> list[dict]:
    """Run validation from all tentacles."""
    results = []
    for t in _registry.values():
        try:
            findings = t.validate(file_path, context)
            results.extend(findings)
        except Exception as e:
            results.append({
                "id": f"{t.name.upper()}-ERR",
                "severity": "error",
                "message": f"Tentacle '{t.name}' error: {e}"
            })
    return results


def init():
    """Discover and register all tentacles."""
    tentacles = discover()
    for t in tentacles.values():
        try:
            register(t)
        except ValueError:
            pass  # Already registered
    return tentacles
