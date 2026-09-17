"""Entry point: build the notebook modules, register the sector packs, serve the app."""

import os
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent

# The build is hash-skipped, so this is a no-op when the image already built it.
subprocess.run([sys.executable, "scripts/build_notebooks.py"], check=True, cwd=ROOT)
sys.path.insert(0, str(ROOT / "automatron_build"))

import automatron_core as core  # noqa: E402

SECTOR_MODULES = (
    "automatron_space",
    "automatron_quant",
    "automatron_ecommerce",
    "automatron_realestate",
)

for _name in SECTOR_MODULES:
    __import__(_name)  # importing a sector pack registers it

app = core.create_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "7860")))
