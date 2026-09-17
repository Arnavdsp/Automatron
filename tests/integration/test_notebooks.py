"""The notebook build produces clean, importable modules."""

import importlib
import sys

import nbformat
import pytest

MODULES = (
    "automatron_core",
    "automatron_space",
    "automatron_quant",
    "automatron_ecommerce",
    "automatron_realestate",
)
SECTOR_MODULES = MODULES[1:]
DROP_TAGS = {"bootstrap", "demo"}


def read_notebook(repo_root, name):
    return nbformat.read(str(repo_root / "notebooks" / f"{name}.ipynb"), as_version=4)


def built_source(build_dir, name):
    return (build_dir / f"{name}.py").read_text(encoding="utf-8")


def test_every_notebook_produces_a_module(repo_root, build_dir):
    for name in MODULES:
        assert (repo_root / "notebooks" / f"{name}.ipynb").exists()
        assert (build_dir / f"{name}.py").exists()
    assert (build_dir / "__init__.py").exists()


@pytest.mark.parametrize("name", MODULES)
def test_module_imports_and_reports_its_name(name):
    assert importlib.import_module(name).hello() == name


@pytest.mark.parametrize("name", MODULES)
def test_no_interactive_code_survives(name, build_dir):
    source = built_source(build_dir, name)
    assert "get_ipython(" not in source
    for lineno, line in enumerate(source.splitlines(), start=1):
        assert not line.strip().startswith(("%", "!")), f"{name}.py:{lineno}"


@pytest.mark.parametrize("name", MODULES)
def test_tagged_cells_are_dropped(name, repo_root, build_dir):
    notebook = read_notebook(repo_root, name)
    source = built_source(build_dir, name)
    for cell in notebook.cells:
        tags = set(cell.get("metadata", {}).get("tags", []))
        if DROP_TAGS & tags:
            assert cell.source.strip() not in source


@pytest.mark.parametrize("name", SECTOR_MODULES)
def test_sector_notebooks_carry_a_bootstrap_cell(name, repo_root):
    notebook = read_notebook(repo_root, name)
    tagged = [
        cell for cell in notebook.cells if "bootstrap" in cell.get("metadata", {}).get("tags", [])
    ]
    assert tagged, "a sector notebook builds the core module before importing it"


@pytest.mark.parametrize("name", MODULES)
def test_notebook_is_committed_clean(name, repo_root):
    notebook = read_notebook(repo_root, name)
    assert notebook.metadata.get("kernelspec", {}).get("name") == "python3"
    assert "colab" not in notebook.metadata
    for index, cell in enumerate(notebook.cells):
        if cell.cell_type == "code":
            assert not cell.get("outputs"), f"{name}.ipynb cell {index} has stored outputs"
            assert cell.get("execution_count") is None


def test_build_flags_interactive_lines(repo_root):
    sys.path.insert(0, str(repo_root / "scripts"))
    import build_notebooks

    assert build_notebooks.check("get_ipython().run_line_magic('pip', 'x')", "n.ipynb")
    assert build_notebooks.check("%pip install x", "n.ipynb")
    assert build_notebooks.check("!ls", "n.ipynb")
    assert not build_notebooks.check("def hello():\n    return 1", "n.ipynb")
