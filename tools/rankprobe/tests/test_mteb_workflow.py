import ast
import builtins
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_mteb_workflow.py"
DOC = SCRIPT.parents[1] / "docs" / "mteb-workflow.md"
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


@pytest.mark.parametrize(
    "scope, message",
    [
        pytest.param(
            '{"validation":{"q":{"d":0.75,"d":0.25}}}',
            "Duplicate JSON key",
            id="duplicate-document-key",
        ),
        pytest.param(
            '{"test":{"q":{"d":0.75}}}',
            "Prediction split not found",
            id="missing-selected-split",
        ),
        pytest.param(
            '{"validation":{"q first":{"d":0.75},"q empty":{}}}',
            "has no score mapping; not dropped",
            id="late-empty-query",
        ),
        pytest.param(
            '{"validation":{"q":{"d first":0.75,"d invalid":"bad"}}}',
            "score must be a finite number",
            id="late-invalid-score",
        ),
        pytest.param(
            '{"validation":{"q":{"d first":0.75,"d invalid":true}}}',
            "score must be a finite number",
            id="late-boolean-score",
        ),
    ],
)
def test_documented_conversion_rejects_before_writing_and_allows_clean_retry(
    tmp_path, monkeypatch, capsys, scope, message
):
    from rankprobe.io import read_predictions

    source_folder = tmp_path / "source files with spaces"
    source_folder.mkdir()
    source = source_folder / "原始 predictions.json"
    destination = source_folder / "selected scores.csv"
    working = tmp_path / "different working directory"
    working.mkdir()
    monkeypatch.chdir(working)
    real_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        assert name.split(".")[0] not in {"mteb", "numpy", "torch", "transformers"}
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    tree = ast.parse(checker.read_recipe(DOC))
    values = {
        "source": ast.parse(f"Path({str(source)!r})", mode="eval").body,
        "destination": ast.parse(f"Path({str(destination)!r})", mode="eval").body,
        "subset": ast.Constant("subset,甲"),
        "split": ast.Constant("validation"),
    }
    changed = set()
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if name in values:
                node.value = values[name]
                changed.add(name)
    assert changed == set(values)
    code = compile(ast.fix_missing_locations(tree), str(DOC), "exec")

    original = (
        '{"mteb_model_meta":{"model_name":null,"revision":null},"subset,甲":'
        + scope + "}\n"
    ).encode("utf-8")
    source.write_bytes(original)
    with pytest.raises(ValueError, match=message):
        exec(code, {"__name__": "__main__"})
    assert source.read_bytes() == original
    assert list(source_folder.iterdir()) == [source]
    assert list(working.iterdir()) == []
    assert capsys.readouterr().out == ""

    corrected = json.dumps({
        "mteb_model_meta": {"model_name": None, "revision": None},
        "subset,甲": {"validation": {
            "query,甲": {"document B": 0.625, 'document,"A"': 0.625, "document C": 0.1},
            "query A": {
                "document Z": 9007199254740993,
                "document Y": 9007199254740992,
                "document X": -9007199254740993,
            },
        }},
        "other subset": {"test": {"unselected query": {"unselected document": 99}}},
    }, ensure_ascii=False).encode("utf-8")
    source.write_bytes(corrected)
    exec(code, {"__name__": "__main__"})
    assert source.read_bytes() == corrected
    assert {(path.name) for path in source_folder.iterdir()} == {source.name, destination.name}
    assert list(working.iterdir()) == []
    rows = read_predictions(destination)
    assert [(row.query_id, row.item_id, row.score, row.relevance) for row in rows] == [
        ("query,甲", "document B", 0.625, None),
        ("query,甲", 'document,"A"', 0.625, None),
        ("query,甲", "document C", 0.1, None),
        ("query A", "document Z", 9007199254740993, None),
        ("query A", "document Y", 9007199254740992, None),
        ("query A", "document X", -9007199254740993, None),
    ]
    assert all(type(row.score) is int for row in rows[3:])
    assert rows[3].score != rows[4].score
