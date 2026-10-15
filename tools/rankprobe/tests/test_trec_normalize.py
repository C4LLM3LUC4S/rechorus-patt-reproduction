import hashlib
import importlib.util
from pathlib import Path

import pytest

from rankprobe.io import InputError, read_predictions
from rankprobe.model import Row

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "normalize_trec_run.py"
SPEC = importlib.util.spec_from_file_location("normalize_trec_run", SCRIPT)
normalizer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(normalizer)


def test_explicit_conversion_preserves_order_scores_duplicates_and_unknowns(tmp_path):
    source, output = tmp_path / "original.txt", tmp_path / "strict.run"
    source.write_text(
        "# comment\n\n001 Q0 z 9 1 tag ignored label=1\n"
        "001 Q0 a 1 1 tag\n001 Q0 z 8 -0.5 tag more fields\n",
        encoding="utf-8-sig",
    )
    before = source.read_bytes()
    with pytest.raises(InputError, match="exactly 6"):
        read_predictions(source, format="trec")
    result = normalizer.normalize_run(source, output)
    assert read_predictions(output) == [Row("001", "z", 1), Row("001", "a", 1), Row("001", "z", -.5)]
    assert result["rows"] == 3
    assert result["rows_with_trailing_fields_removed"] == 2
    assert result["source_sha256"] == hashlib.sha256(before).hexdigest()
    assert result["output_sha256"] == hashlib.sha256(output.read_bytes()).hexdigest()
    assert source.read_bytes() == before


@pytest.mark.parametrize("body", [
    "q Q0 d 1 2", "q Q0 d -1 2 tag tail", "q Q0 d 1 NaN tag tail",
    "q Q0 d 1 2 tag tail\x00", "# empty\n",
])
def test_invalid_input_never_creates_output(tmp_path, body):
    source, output = tmp_path / "bad.txt", tmp_path / "strict.run"
    source.write_text(body, encoding="utf-8")
    before = source.read_bytes()
    with pytest.raises(ValueError):
        normalizer.normalize_run(source, output)
    assert not output.exists()
    assert source.read_bytes() == before


def test_no_overwrite_source_or_existing_output(tmp_path):
    source, output = tmp_path / "original.run", tmp_path / "strict.run"
    source.write_text("q Q0 d 1 2 tag tail\n", encoding="utf-8")
    before = source.read_bytes()
    with pytest.raises(ValueError, match="source"):
        normalizer.normalize_run(source, source)
    output.write_bytes(b"keep")
    with pytest.raises(ValueError, match="already exists"):
        normalizer.normalize_run(source, output)
    assert output.read_bytes() == b"keep"
    assert source.read_bytes() == before


def test_cli_reports_failure_without_a_traceback(tmp_path, capsys):
    result = normalizer.main([str(tmp_path / "absent"), str(tmp_path / "out.run")])
    assert result == 2
    assert "Normalization failed:" in capsys.readouterr().err
