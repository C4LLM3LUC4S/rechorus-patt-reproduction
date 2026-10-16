import builtins
import importlib.util
from pathlib import Path
import subprocess
import sys

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_mteb_workflow.py"
SPEC = importlib.util.spec_from_file_location("check_mteb_workflow", SCRIPT)
checker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checker)

RECIPE_CODE = (
    'from pathlib import Path\n'
    'from rankprobe.model import Row\n'
    'source = Path("scores.jsonl")\n'
    'destination = Path("rows.csv")\n'
    'subset = "toy"\n'
    'split = "test"\n'
)


def test_existing_output_preserves_sentinel_before_optional_imports(tmp_path, monkeypatch):
    out = tmp_path / "existing"
    out.mkdir()
    sentinel = out / "summary.json"
    sentinel.write_bytes(b"keep original")
    real_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        assert name.split(".")[0] not in {"mteb", "numpy", "torch", "transformers"}
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    with pytest.raises(checker.GateError, match="must be new|already exists|existing"):
        checker.check_workflow(out)
    assert sentinel.read_bytes() == b"keep original"
    assert list(out.iterdir()) == [sentinel]


def test_missing_parent_is_rejected_without_creating_directories(tmp_path):
    parent = tmp_path / "absent-parent"
    with pytest.raises(checker.GateError, match="parent"):
        checker.check_workflow(parent / "out")
    assert not parent.exists()


def test_symlink_output_is_rejected_without_changing_target(tmp_path):
    target = tmp_path / "original"
    target.mkdir()
    sentinel = target / "keep.txt"
    sentinel.write_bytes(b"preserve target")
    link = tmp_path / "linked-output"
    try:
        link.symlink_to(target, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("creating symlinks is unavailable in this environment")
    with pytest.raises(checker.GateError, match="output:.*must be new"):
        checker.check_workflow(link)
    assert link.is_symlink()
    assert sentinel.read_bytes() == b"preserve target"
    assert list(target.iterdir()) == [sentinel]


def test_symlink_ancestor_is_rejected_without_writing_target(tmp_path):
    target = tmp_path / "original"
    target.mkdir()
    link = tmp_path / "linked-parent"
    try:
        link.symlink_to(target, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("creating symlinks is unavailable in this environment")
    with pytest.raises(checker.GateError, match="output:.*(?:linked|symbolic|symlink)"):
        checker.check_workflow(link / "out")
    assert list(target.iterdir()) == []


def test_missing_recipe_is_rejected_before_creating_output(tmp_path):
    out = tmp_path / "new-output"
    with pytest.raises(checker.GateError, match="recipe"):
        checker.check_workflow(out, recipe=tmp_path / "absent-private-recipe.md")
    assert not out.exists()


def test_isolated_cli_without_optional_packages_has_bounded_failure(tmp_path):
    out = tmp_path / "private-output-name"
    process = subprocess.run(
        [sys.executable, "-I", "-S", str(SCRIPT), "--out", str(out)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    output = process.stdout + process.stderr
    assert process.returncode == 2
    assert not out.exists()
    assert "Traceback" not in output
    assert str(tmp_path) not in output
    assert out.name not in output
    assert output.strip()


def test_read_recipe_accepts_one_configurable_python_block(tmp_path):
    recipe = tmp_path / "recipe.md"
    recipe.write_text(f"# Example\n\n```python\n{RECIPE_CODE}```\n", encoding="utf-8")
    assert checker.read_recipe(recipe).strip() == RECIPE_CODE.strip()
    assert list(tmp_path.iterdir()) == [recipe]


def test_read_recipe_rejects_empty_multiple_or_unrelated_blocks(tmp_path):
    recipe = tmp_path / "recipe.md"
    invalid_documents = (
        "# No Python block\n",
        "```python\n```\n",
        "```python\npass\n```\n```python\npass\n```\n",
        f"```python\n{RECIPE_CODE}```\n```python\n{RECIPE_CODE}```\n",
        "```python\nprint('unrelated')\n```\n",
    )
    for text in invalid_documents:
        recipe.write_text(text, encoding="utf-8")
        before = recipe.read_bytes()
        with pytest.raises(checker.GateError, match="recipe"):
            checker.read_recipe(recipe)
        assert recipe.read_bytes() == before
