import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/publish_github_release.py"
SPEC = importlib.util.spec_from_file_location("publish_github_release", SCRIPT)
release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release)
COMMIT = "a" * 40


@pytest.fixture
def assets(tmp_path):
    directory = tmp_path / "assets"
    directory.mkdir()
    files = {
        "RankProbe-0.1.0a4.zip": b"original bundle",
        "rankprobe-0.1.0a4-py3-none-any.whl": b"original wheel",
        "rankprobe-0.1.0a4.tar.gz": b"original source",
        "RELEASE_INFO.json": json.dumps({
            "version": "0.1.0a4", "source_commit": COMMIT,
            "repository": release.REPOSITORY, "ci_url": None,
        }).encode(),
    }
    for name, data in files.items():
        (directory / name).write_bytes(data)
    (directory / "SHA256SUMS").write_text("".join(
        f"{hashlib.sha256(data).hexdigest()}  {name}\n" for name, data in files.items()
    ), encoding="utf-8")
    return directory


def no_network(*args, **kwargs):
    raise AssertionError("Network/gh call before explicit checked publication")


def test_dry_run_has_no_network_or_mutation(assets, monkeypatch, capsys):
    monkeypatch.setattr(release, "gh", no_network)
    before = {path.name: path.read_bytes() for path in assets.iterdir()}
    release.publish(assets, assets / "absent-notes.md")
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["network_or_mutation"] is False
    assert len(receipt["assets"]) == 5
    assert {path.name: path.read_bytes() for path in assets.iterdir()} == before


def test_changed_asset_stops_before_network(assets, monkeypatch):
    monkeypatch.setattr(release, "gh", no_network)
    (assets / "RankProbe-0.1.0a4.zip").write_bytes(b"changed")
    with pytest.raises(ValueError, match="checksum mismatch"):
        release.publish(assets, assets / "absent", True)


@pytest.mark.parametrize("name", ["../private.csv", "dir/private.csv", "dir\\private.csv"])
def test_checksum_paths_cannot_leave_asset_folder(assets, name, monkeypatch):
    monkeypatch.setattr(release, "gh", no_network)
    (assets / "SHA256SUMS").write_text("0" * 64 + "  " + name + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Unsafe"):
        release.publish(assets, assets / "absent", True)


def test_duplicate_checksum_stops_before_network(assets, monkeypatch):
    monkeypatch.setattr(release, "gh", no_network)
    sums = assets / "SHA256SUMS"
    text = sums.read_text(encoding="utf-8")
    sums.write_text(text + text.splitlines()[0] + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        release.publish(assets, assets / "absent", True)


def test_unlisted_file_stops_before_network(assets, monkeypatch):
    monkeypatch.setattr(release, "gh", no_network)
    (assets / "private.csv").write_text("do not upload", encoding="utf-8")
    with pytest.raises(ValueError, match="asset list differs"):
        release.publish(assets, assets / "absent", True)


def prepare_draft(assets, monkeypatch, corrupt_download=False, wrong_commit=False):
    calls = []
    remote = {
        "tag_name": "v0.1.0a4", "target_commitish": "b" * 40 if wrong_commit else COMMIT,
        "draft": True, "prerelease": True, "html_url": "https://github.com/example/release",
        "assets": [{"name": path.name} for path in assets.iterdir()],
    }

    def fake_gh(*arguments, **kwargs):
        calls.append(arguments)
        if arguments[:2] == ("release", "download"):
            destination = Path(arguments[-1])
            for path in assets.iterdir():
                data = b"changed in transit" if corrupt_download and path.suffix == ".zip" else path.read_bytes()
                (destination / path.name).write_bytes(data)
            return SimpleNamespace(stdout="", returncode=0)
        if arguments[:2] == ("release", "edit"):
            remote["draft"] = False
            return SimpleNamespace(stdout="", returncode=0)
        if arguments[0] == "api":
            if "releases?" in arguments[1]:
                result = [remote]
            elif "git/ref/" in arguments[1]:
                result = {"object": {"type": "commit", "sha": COMMIT}}
            else:
                result = remote
            return SimpleNamespace(stdout=json.dumps(result), returncode=0)
        raise AssertionError(arguments)

    monkeypatch.setattr(release, "gh", fake_gh)
    monkeypatch.setattr(release.subprocess, "check_output", lambda *args, **kwargs: COMMIT.encode())
    return calls, remote


def test_changed_remote_bytes_leave_draft_unpublished(assets, monkeypatch):
    calls, remote = prepare_draft(assets, monkeypatch, corrupt_download=True)
    with pytest.raises(ValueError, match="Downloaded release asset mismatch"):
        release.publish(assets, assets / "notes", True)
    assert remote["draft"] is True
    assert not any(call[:2] == ("release", "edit") for call in calls)


def test_other_commit_draft_is_not_replaced(assets, monkeypatch):
    calls, remote = prepare_draft(assets, monkeypatch, wrong_commit=True)
    with pytest.raises(ValueError, match="another source identity"):
        release.publish(assets, assets / "notes", True)
    assert remote["draft"] is True
    assert all(call[0] == "api" for call in calls)


def test_published_version_is_not_replaced_by_later_main(assets, monkeypatch, capsys):
    calls, remote = prepare_draft(assets, monkeypatch, wrong_commit=True)
    remote["draft"] = False
    release.publish(assets, assets / "notes", True)
    assert all(call[0] == "api" for call in calls)
    assert json.loads(capsys.readouterr().out)["new_publication"] is False


def test_verified_draft_publishes_after_all_downloads(assets, monkeypatch, capsys):
    calls, remote = prepare_draft(assets, monkeypatch)
    release.publish(assets, assets / "notes", True)
    actions = [call[1] for call in calls if call[0] == "release"]
    assert actions == ["download", "edit"]
    assert remote["draft"] is False
    assert json.loads(capsys.readouterr().out)["assets_verified"] == 5
