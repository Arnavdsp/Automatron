"""Convert the notebooks under notebooks/ into importable modules.

Application logic lives in notebooks, but hosting platforms need plain modules,
so this step renders each notebook to automatron_build/<name>.py. Cells tagged
'bootstrap' or 'demo' exist only for interactive use and are dropped. The build
is skipped when no notebook has changed since the last run.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NOTEBOOK_DIR = ROOT / "notebooks"
BUILD_DIR = ROOT / "automatron_build"
HASH_FILE = BUILD_DIR / ".hashes.json"

DROP_TAGS = ("bootstrap", "demo")

# nbconvert rewrites magics and shell escapes into this call rather than
# dropping them, so its presence means interactive-only code reached the build.
BANNED_CALL = "get_ipython("


def notebook_paths() -> list[Path]:
    return sorted(NOTEBOOK_DIR.glob("*.ipynb"))


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_hashes() -> dict[str, str]:
    if not HASH_FILE.exists():
        return {}
    try:
        return json.loads(HASH_FILE.read_text(encoding="utf-8"))
    except ValueError:
        return {}


def export(path: Path) -> str:
    import nbformat
    from nbconvert import PythonExporter
    from traitlets.config import Config

    config = Config()
    config.TagRemovePreprocessor.enabled = True
    config.TagRemovePreprocessor.remove_cell_tags = DROP_TAGS
    config.PythonExporter.preprocessors = ["nbconvert.preprocessors.TagRemovePreprocessor"]

    notebook = nbformat.read(path, as_version=4)
    source, _ = PythonExporter(config=config).from_notebook_node(notebook)
    return source


def check(source: str, name: str) -> list[str]:
    problems = []
    for lineno, line in enumerate(source.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith(("%", "!")):
            problems.append(f"{name}:{lineno}: interactive line survived: {stripped[:60]}")
        elif BANNED_CALL in line:
            problems.append(f"{name}:{lineno}: {BANNED_CALL} survived the build")
    return problems


def main() -> int:
    paths = notebook_paths()
    if not paths:
        print("no notebooks found under notebooks/", file=sys.stderr)
        return 1

    BUILD_DIR.mkdir(exist_ok=True)
    init_file = BUILD_DIR / "__init__.py"
    current = {path.name: file_hash(path) for path in paths}
    built = all((BUILD_DIR / f"{path.stem}.py").exists() for path in paths)

    if built and init_file.exists() and load_hashes() == current:
        print("notebooks unchanged; build skipped")
        return 0

    problems: list[str] = []
    rendered: dict[str, str] = {}
    for path in paths:
        try:
            source = export(path)
        except Exception as exc:
            print(f"{path.name}: export failed: {exc}", file=sys.stderr)
            return 1
        problems.extend(check(source, path.name))
        rendered[path.stem] = source

    if problems:
        for problem in problems:
            print(problem, file=sys.stderr)
        return 1

    for stem, source in rendered.items():
        (BUILD_DIR / f"{stem}.py").write_text(source, encoding="utf-8")
    init_file.write_text(
        '"""Modules generated from the notebooks under notebooks/."""\n',
        encoding="utf-8",
    )
    HASH_FILE.write_text(json.dumps(current, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"built {len(rendered)} module(s) into {BUILD_DIR.name}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
