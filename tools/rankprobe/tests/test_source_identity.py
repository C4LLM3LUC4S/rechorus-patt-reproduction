"""Source identity describes readable package bytes, not loaded code or an environment."""

import hashlib
from importlib import resources
import json
from pathlib import Path

import rankprobe
from rankprobe import cli


CORE_MODULES = {
    "__init__.py", "__main__.py", "audit.py", "cli.py", "demo.py",
    "io.py", "metrics.py", "model.py", "report.py",
}


def copy_core_resources(destination):
    destination.mkdir(parents=True)
    package = resources.files("rankprobe")
    for name in CORE_MODULES:
        (destination / name).write_bytes(package.joinpath(name).read_bytes())
    return destination


def test_current_identity_covers_nine_modules_without_paths_or_source_text():
    identity = cli._core_source_identity()
    package = resources.files("rankprobe")
    current_modules = {
        item.name for item in package.iterdir() if item.is_file() and item.name.endswith(".py")
    }
    assert current_modules == CORE_MODULES
    assert set(identity) == {"scheme", "status", "sha256", "files"}
    assert identity["scheme"] == "rankprobe-core-python-v1"
    assert identity["status"] == "available"
    assert set(identity["files"]) == CORE_MODULES
    assert len(identity["sha256"]) == 64
    assert all(character in "0123456789abcdef" for character in identity["sha256"])
    for name, file_hash in identity["files"].items():
        assert file_hash == hashlib.sha256(package.joinpath(name).read_bytes()).hexdigest()
        assert not Path(name).is_absolute()
    serialized = json.dumps(identity)
    assert json.dumps(str(Path(rankprobe.__file__).resolve().parent))[1:-1] not in serialized
    assert "def _core_source_identity" not in serialized
    assert "import argparse" not in serialized


def test_changing_only_core_resource_bytes_changes_same_version_identity(tmp_path, monkeypatch):
    package = copy_core_resources(tmp_path / "source resources")
    monkeypatch.setattr(cli, "files", lambda _package: package)
    version_before = rankprobe.__version__
    before = cli._core_source_identity()
    source = package / "metrics.py"
    source.write_bytes(source.read_bytes() + b"\n# Original test-only byte change.\n")
    after = cli._core_source_identity()
    assert rankprobe.__version__ == version_before
    assert before["status"] == after["status"] == "available"
    assert before["sha256"] != after["sha256"]
    assert before["files"]["__init__.py"] == after["files"]["__init__.py"]
    assert {
        name for name in CORE_MODULES if before["files"][name] != after["files"][name]
    } == {"metrics.py"}


def test_resource_location_and_documentation_do_not_change_identity(tmp_path, monkeypatch):
    first = copy_core_resources(tmp_path / "first source location")
    second = copy_core_resources(tmp_path / "relocated source")
    (first / "README.md").write_text("Original documentation.\n", encoding="utf-8")
    (second / "README.md").write_text("Different documentation.\n", encoding="utf-8")
    monkeypatch.setattr(cli, "files", lambda _package: first)
    initial = cli._core_source_identity()
    (first / "README.md").write_text("Changed documentation only.\n", encoding="utf-8")
    assert cli._core_source_identity() == initial
    monkeypatch.setattr(cli, "files", lambda _package: second)
    assert cli._core_source_identity() == initial


def test_unreadable_source_is_explicit_but_does_not_block_cli_report(tmp_path, monkeypatch, capsys):
    package = copy_core_resources(tmp_path / "source resources")

    class UnreadableFile:
        def read_bytes(self):
            raise PermissionError(f"Unreadable original test resource: {package / 'metrics.py'}")

    class PartiallyUnreadablePackage:
        def joinpath(self, name):
            return UnreadableFile() if name == "metrics.py" else package / name

    monkeypatch.setattr(cli, "files", lambda _package: PartiallyUnreadablePackage())
    output = tmp_path / "unavailable report"
    assert cli.main(["demo", "--out", str(output), "--fail-on", "never"]) == 0
    report = json.loads((output / "report.json").read_text("utf-8"))
    identity = report["provenance"]["core_source_identity"]
    assert identity["status"] == "unavailable"
    assert identity["reason"]
    assert "files" not in identity and "sha256" not in identity
    assert json.dumps(str(package))[1:-1] not in json.dumps(identity)
    html = (output / "report.html").read_text("utf-8")
    assert "unavailable" in html and identity["reason"] in html
    assert capsys.readouterr().err == ""


def test_audit_compare_and_demo_record_same_identity_in_json_and_html(tmp_path, capsys):
    source = tmp_path / "original.csv"
    source.write_text("query_id,item_id,score\nquery-1,item-1,1\n", encoding="utf-8")
    expected = cli._core_source_identity()
    assert expected["status"] == "available"
    commands = {
        "audit": ["audit", str(source)],
        "compare": ["compare", "--run", f"left={source}", "--run", f"right={source}"],
        "demo": ["demo"],
    }
    identities = []
    for command, arguments in commands.items():
        output = tmp_path / command
        assert cli.main([*arguments, "--out", str(output), "--fail-on", "never"]) == 0
        report = json.loads((output / "report.json").read_text("utf-8"))
        provenance = report["provenance"]
        assert provenance["rankprobe_version"] == rankprobe.__version__
        assert provenance["command"] == command
        assert provenance["core_source_identity"] == expected
        html = (output / "report.html").read_text("utf-8")
        assert expected["scheme"] in html and expected["sha256"] in html
        assert all(filename in html for filename in CORE_MODULES)
        assert all(file_hash in html for file_hash in expected["files"].values())
        identities.append(provenance["core_source_identity"])
    assert identities[0] == identities[1] == identities[2]
    assert capsys.readouterr().err == ""
