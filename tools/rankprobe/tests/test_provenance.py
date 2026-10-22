from unittest.mock import patch

import pytest

from rankprobe import __version__
from rankprobe.cli import _load_checked, main
from rankprobe.io import read_predictions


def test_rejects_source_changed_during_load(tmp_path):
    source = tmp_path / "run.csv"
    source.write_text("query_id,item_id,score,relevance\nq,a,1,1\n", encoding="utf-8")

    def changing_loader(path):
        rows = read_predictions(path)
        path.write_text("query_id,item_id,score,relevance\nq,a,0,0\n", encoding="utf-8")
        return rows

    with pytest.raises(ValueError, match="input changed"):
        _load_checked(source, changing_loader, "predictions")


def test_cli_version_is_package_version(capsys):
    with pytest.raises(SystemExit) as result:
        main(["--version"])
    assert result.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_changed_source_emits_no_report(tmp_path):
    source = tmp_path / "run.csv"
    source.write_text("query_id,item_id,score,relevance\nq,a,1,1\n", encoding="utf-8")

    def changed(path):
        rows = read_predictions(path)
        path.write_text("query_id,item_id,score,relevance\nq,a,0,0\n", encoding="utf-8")
        return rows

    with patch("rankprobe.cli.read_predictions", changed):
        assert main(["audit", str(source), "--out", str(tmp_path / "report")]) == 2
    assert not (tmp_path / "report" / "report.json").exists()
