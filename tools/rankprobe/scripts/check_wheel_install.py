"""Exercise one built RankProbe wheel offline, outside the source checkout."""

from __future__ import annotations

import argparse
from email.parser import BytesParser
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import zipfile


class GateError(ValueError):
    """A named installation or execution gate did not pass."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise GateError(message)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def clean_environment(venv: Path) -> dict[str, str]:
    allowed = {
        "PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "TMPDIR", "LANG",
        "LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH", "LC_ALL", "LC_CTYPE", "LC_MESSAGES",
    }
    environment = {
        name: os.environ[name] for name in allowed if name in os.environ
    }
    scripts = venv / ("Scripts" if os.name == "nt" else "bin")
    environment.update({
        "PATH": str(scripts) + os.pathsep + environment.get("PATH", ""),
        "VIRTUAL_ENV": str(venv),
        "PIP_CONFIG_FILE": os.devnull,
        "PIP_NO_INDEX": "1",
        "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        "PYTHONNOUSERSITE": "1",
    })
    return environment


def run(
    stage: str, arguments: list[str], *, cwd: Path, environment: dict[str, str],
    expected_error: str | None = None,
) -> str:
    try:
        result = subprocess.run(
            arguments, cwd=cwd, env=environment, shell=False, check=False,
            capture_output=True, encoding="utf-8", errors="replace", timeout=180,
        )
    except subprocess.TimeoutExpired as exc:
        raise GateError(f"{stage}: exceeded 180 seconds") from exc
    except OSError as exc:
        raise GateError(f"{stage}: could not start the subprocess") from exc
    if expected_error is None:
        require(result.returncode == 0, f"{stage}: subprocess exited {result.returncode}")
    else:
        require(result.returncode == 2, f"{stage}: expected invalid-input/output status 2")
        require(not result.stdout, f"{stage}: refusal wrote success output")
        require(expected_error in result.stderr, f"{stage}: expected diagnostic missing")
        require("Traceback" not in result.stderr, f"{stage}: refusal exposed a traceback")
    # Captured output can contain local paths. Only explicit validation results
    # are printed or retained in the summary.
    return result.stdout.strip()


SNAPSHOT = """
import importlib.metadata as metadata
import json
print(json.dumps(sorted(d.metadata['Name'].lower().replace('_', '-')
                        for d in metadata.distributions())))
"""


PROBE = """
import importlib.metadata as metadata
import json
from pathlib import Path
import sys
from urllib.parse import unquote, urlparse
import rankprobe

venv, checkout = (Path(value).resolve() for value in sys.argv[1:3])
distribution = metadata.distribution('rankprobe')
installation = Path(distribution.locate_file('')).resolve()
module = Path(rankprobe.__file__).resolve()
direct = json.loads(distribution.read_text('direct_url.json') or '{}')
archive = direct.get('archive_info', {})
wheel_hash = archive.get('hashes', {}).get('sha256')
if wheel_hash is None and archive.get('hash', '').startswith('sha256='):
    wheel_hash = archive['hash'].split('=', 1)[1]
url = urlparse(direct.get('url', ''))
print(json.dumps({
    'module_version': rankprobe.__version__,
    'distribution_version': distribution.version,
    'isolated': sys.flags.isolated == 1,
    'prefix_matches_venv': Path(sys.prefix).resolve() == venv,
    'prefix_differs_from_base': Path(sys.prefix).resolve() != Path(sys.base_prefix).resolve(),
    'installation_inside_venv': installation.is_relative_to(venv),
    'module_inside_installation': module.is_relative_to(installation),
    'module_inside_venv': module.is_relative_to(venv),
    'module_outside_checkout': not module.is_relative_to(checkout),
    'direct_url_is_local_wheel': url.scheme == 'file',
    'wheel_basename': Path(unquote(url.path)).name,
    'wheel_sha256': wheel_hash,
    'requirements': distribution.metadata.get_all('Requires-Dist', []),
    'distributions': sorted(d.metadata['Name'].lower().replace('_', '-')
                            for d in metadata.distributions()),
}))
"""


def read_report(directory: Path, version: str, report_type: str, source_identity: dict) -> dict:
    require((directory / "report.html").is_file(), f"{report_type}: HTML report missing")
    require((directory / "report.html").stat().st_size > 0, f"{report_type}: HTML report empty")
    try:
        report = json.loads((directory / "report.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise GateError(f"{report_type}: JSON report missing or invalid") from exc
    require(report["report_type"] == report_type, f"{report_type}: wrong report type")
    require(
        report["provenance"]["rankprobe_version"] == version,
        f"{report_type}: report version differs from wheel",
    )
    require(
        report["provenance"].get("core_source_identity") == source_identity,
        f"{report_type}: report core-source identity differs from wheel bytes",
    )
    return report


def check(wheel: Path, checkout: Path) -> dict:
    require(wheel.is_file(), "wheel: explicit --wheel file does not exist")
    require(wheel.suffix == ".whl", "wheel: --wheel must name a .whl file")
    wheel_hash = digest(wheel)
    with zipfile.ZipFile(wheel) as package:
        names = [name for name in package.namelist() if name.endswith(".dist-info/METADATA")]
        require(len(names) == 1, "wheel: expected exactly one distribution metadata file")
        metadata = BytesParser().parsebytes(package.read(names[0]))
        core_hashes = {
            name.removeprefix("rankprobe/"): hashlib.sha256(package.read(name)).hexdigest()
            for name in package.namelist()
            if name.startswith("rankprobe/") and name.count("/") == 1 and name.endswith(".py")
        }
        require(bool(core_hashes), "wheel: core Python source files are missing")
        manifest = json.dumps(core_hashes, sort_keys=True, separators=(",", ":")).encode("ascii")
        source_identity = {
            "scheme": "rankprobe-core-python-v1", "status": "available",
            "sha256": hashlib.sha256(manifest).hexdigest(), "files": core_hashes,
        }
    require(metadata["Name"] == "rankprobe", "wheel: metadata name must be rankprobe")
    version = metadata["Version"]
    require(bool(version), "wheel: metadata version is missing")
    requirements = metadata.get_all("Requires-Dist", [])
    # This gate is for this project's wheel, whose declared optional requirements
    # all use a single extra marker. It is not a general PEP 508 validator.
    extra_markers = tuple(
        f'; extra == "{extra}"' for extra in metadata.get_all("Provides-Extra", [])
    )
    require(
        all(requirement.count(";") == 1 and requirement.endswith(extra_markers)
            for requirement in requirements),
        "wheel: unexpected core runtime dependency",
    )
    fixtures = {
        name: checkout / "examples" / "trec" / name
        for name in ("baseline.run", "reordered.run", "judgments.qrels")
    }
    fixture_hashes = {name: digest(path) for name, path in fixtures.items()}
    with tempfile.TemporaryDirectory(prefix="rankprobe wheel gate ") as directory:
        workspace = Path(directory).resolve()
        require(not workspace.is_relative_to(checkout), "temporary workspace is inside checkout")
        venv = workspace / "clean environment"
        environment = clean_environment(venv)
        run(
            "create fresh venv", [sys.executable, "-I", "-m", "venv", str(venv)],
            cwd=workspace, environment=environment,
        )
        scripts = venv / ("Scripts" if os.name == "nt" else "bin")
        python = scripts / ("python.exe" if os.name == "nt" else "python")
        console = scripts / ("rankprobe.exe" if os.name == "nt" else "rankprobe")
        before = set(json.loads(run(
            "baseline installed distributions", [str(python), "-I", "-c", SNAPSHOT],
            cwd=workspace, environment=environment,
        )))
        require("rankprobe" not in before, "fresh venv unexpectedly contains rankprobe")
        run(
            "offline wheel installation",
            [str(python), "-I", "-m", "pip", "--isolated", "install", "--no-index",
             "--no-deps", "--disable-pip-version-check", "--no-cache-dir",
             f"{wheel.as_uri()}#sha256={wheel_hash}"],
            cwd=workspace, environment=environment,
        )
        probe = json.loads(run(
            "installed package probe",
            [str(python), "-I", "-c", PROBE, str(venv), str(checkout)],
            cwd=workspace, environment=environment,
        ))
        flags = (
            "isolated", "prefix_matches_venv", "prefix_differs_from_base",
            "installation_inside_venv", "module_inside_installation",
            "module_inside_venv", "module_outside_checkout", "direct_url_is_local_wheel",
        )
        for flag in flags:
            require(probe[flag] is True, f"installed package isolation failed: {flag}")
        require(
            probe["module_version"] == probe["distribution_version"] == version,
            "installed package version differs from wheel metadata",
        )
        require(probe["wheel_basename"] == wheel.name, "installed wheel basename differs")
        require(probe["wheel_sha256"] == wheel_hash, "installed wheel SHA256 differs")
        require(probe["requirements"] == requirements, "installed dependency metadata differs")
        after = set(probe["distributions"])
        require(after - before == {"rankprobe"}, "installation added unexpected distributions")
        require(before <= after, "installation removed baseline distributions")
        expected_version = f"RankProbe {version}"
        for name, command in (
            ("isolated module", [str(python), "-I", "-m", "rankprobe"]),
            ("console launcher", [str(console)]),
        ):
            output = run(f"{name} version", [*command, "--version"],
                         cwd=workspace, environment=environment)
            require(output == expected_version, f"{name}: unexpected version output")
            scores = workspace / f"{name} scores.csv"
            recovery_directory = workspace / f"{name} recovery reports"
            scores.write_text("query_id,item_id,score\nq1,a,1\nq1,b,not-a-number\n",
                              encoding="utf-8")
            original_hash = digest(scores)
            audit_command = [*command, "audit", str(scores), "--cutoffs", "1,2",
                             "--out", str(recovery_directory)]
            run(f"{name} invalid input", audit_command, cwd=workspace, environment=environment,
                expected_error="score must be a finite number")
            require(digest(scores) == original_hash, f"{name}: refused input changed")
            require(not recovery_directory.exists(), f"{name}: refused input created output")
            # Correct only this gate's invented fixture; real source records are never edited.
            scores.write_text("query_id,item_id,score\nq1,a,1\nq1,b,0\n", encoding="utf-8")
            corrected_hash = digest(scores)
            run(f"{name} corrected retry", audit_command, cwd=workspace, environment=environment)
            retry = read_report(recovery_directory, version, "audit", source_identity)
            require(retry["summary"]["rows"] == 2, f"{name}: retry dropped an input row")
            require(retry["summary"]["unknown_candidates"] == 2,
                    f"{name}: retry invented judgments")
            require(retry["summary"]["assumed_nonrelevant_candidates"] == 0,
                    f"{name}: retry assumed nonrelevance")
            require(retry["protocol"]["unjudged"] == "unknown"
                    and retry["protocol"]["qrels_complete"] is False,
                    f"{name}: retry changed judgment policy")
            require(all(metric["value"] is None and metric["status"] == "not_checked"
                        for metric in retry["metrics"].values()),
                    f"{name}: retry invented label-dependent metrics")
            sources = retry["provenance"]["sources"]
            require(len(sources) == 1 and sources[0]["filename"] == scores.name
                    and sources[0]["sha256"] == corrected_hash
                    and sources[0]["input_format"] == "csv",
                    f"{name}: retry input provenance differs")
            reports = {recovery_directory / filename for filename in ("report.json", "report.html")}
            report_hashes = {path: digest(path) for path in reports}
            run(f"{name} existing reports", audit_command, cwd=workspace, environment=environment,
                expected_error="Choose a new --out")
            require(all(digest(path) == value for path, value in report_hashes.items()),
                    f"{name}: refusal changed existing reports")
            require(digest(scores) == corrected_hash, f"{name}: corrected input changed")
        demo_directory = workspace / "demo reports"
        run(
            "console demo", [str(console), "demo", "--out", str(demo_directory)],
            cwd=workspace, environment=environment,
        )
        demo = read_report(demo_directory, version, "audit", source_identity)
        require(bool(demo.get("demo_note")), "demo: synthetic example notice missing")
        require(demo["summary"]["unknown_candidates"] == 1, "demo: unknown labels changed")
        require(demo["summary"]["duplicate_rows"] == 1, "demo: duplicate example missing")
        inputs = workspace / "synthetic inputs"
        inputs.mkdir()
        copied = {}
        for name, source in fixtures.items():
            copied[name] = inputs / name
            shutil.copyfile(source, copied[name])
            require(digest(copied[name]) == fixture_hashes[name], "fixture copy differs")
        compare_directory = workspace / "comparison reports"
        run(
            "isolated TREC comparison",
            [str(python), "-I", "-m", "rankprobe", "compare",
             "--run", f"baseline={copied['baseline.run']}",
             "--run", f"reordered={copied['reordered.run']}",
             "--qrels", str(copied["judgments.qrels"]), "--cutoffs", "1,2",
             "--out", str(compare_directory)],
            cwd=workspace, environment=environment,
        )
        report = read_report(compare_directory, version, "compare", source_identity)
        require(report["protocol"]["unjudged"] == "unknown", "compare: unknown policy changed")
        ideal_discount = 1 / math.log2(3)
        for name, expected_mrr, expected_ndcg, eligible in (
            ("baseline", 0.25, ideal_discount / 2, ["q1", "q2"]),
            ("reordered", 0.5, ideal_discount, ["q1"]),
        ):
            audit = report["runs"][name]["audit"]
            metric = audit["metrics"]["mrr@2"]
            require(
                math.isclose(metric["value"], expected_mrr, rel_tol=0, abs_tol=1e-12),
                "compare: MRR differs",
            )
            require(
                math.isclose(audit["metrics"]["ndcg@2"]["value"], expected_ndcg,
                             rel_tol=0, abs_tol=1e-12),
                "compare: NDCG differs",
            )
            require(metric["eligible_query_ids"] == eligible, "compare: eligible query IDs differ")
            require(metric["excluded_query_ids"] == ["q3"], "compare: unknown query not excluded")
            require(audit["metrics"]["recall@2"]["value"] is None, "compare: Recall invented")
            require(audit["summary"]["unknown_candidates"] == 1, "compare: unknown label lost")
        matched = report["pairs"][0]["matched_pool_comparison"]
        for metric in ("mrr@2", "ndcg@2"):
            require(
                matched["delta_right_minus_left"][metric]["delta"] == 0,
                "compare: matched-pool delta differs",
            )
        for side in ("left_metrics", "right_metrics"):
            require(
                matched[side]["mrr@2"]["excluded_query_ids"] == ["q3"],
                "compare: matched-pool unknown query not excluded",
            )
        sources = {source["filename"]: source for source in report["provenance"]["sources"]}
        require(set(sources) == set(fixtures), "compare: provenance source list differs")
        for name, source in sources.items():
            require(source["sha256"] == fixture_hashes[name], "compare: provenance SHA256 differs")
            require(source["input_format"] == "trec", "compare: TREC provenance missing")
        for name, path in fixtures.items():
            require(digest(path) == fixture_hashes[name], "source fixture changed during check")
        require(digest(wheel) == wheel_hash, "source wheel changed during check")
    return {
        "status": "passed", "wheel": wheel.name, "wheel_sha256": wheel_hash,
        "version": version, "python": platform.python_version(), "platform": sys.platform,
        "checks": {
            **{flag: True for flag in flags}, "offline_no_dependencies_install": True,
            "only_rankprobe_added": True, "wheel_origin_and_version_match": True,
            "module_and_console_versions": True, "console_demo_reports": True,
            "isolated_trec_comparison": True, "unknown_labels_preserved": True,
            "matched_pool_delta_zero": True, "report_source_hashes_match": True,
            "source_inputs_unchanged": True,
            "report_core_identity_matches_wheel": True,
            "installed_entrypoints_reject_invalid_input": True,
            "installed_entrypoints_clean_retry_preserves_unknowns": True,
            "installed_entrypoints_preserve_existing_reports": True,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", required=True, type=Path, help="explicit built wheel file")
    parser.add_argument("--summary", type=Path, help="write a path-free JSON summary; must be new")
    arguments = parser.parse_args()
    if arguments.summary and (arguments.summary.exists() or arguments.summary.is_symlink()):
        parser.error("--summary must name a new file; existing paths are never replaced")
    try:
        result = check(arguments.wheel.resolve(), Path(__file__).resolve().parents[1])
    except (ValueError, OSError, KeyError, TypeError, zipfile.BadZipFile) as exc:
        # Product errors can contain absolute paths. Keep the public diagnostic
        # bounded to our own gate descriptions and the exception type otherwise.
        reason = str(exc) if isinstance(exc, GateError) else type(exc).__name__
        result = {"status": "failed", "reason": reason}
    if arguments.summary:
        try:
            arguments.summary.parent.mkdir(parents=True, exist_ok=True)
            with arguments.summary.open("x", encoding="utf-8", newline="\n") as handle:
                json.dump(result, handle, indent=2, ensure_ascii=True, allow_nan=False)
                handle.write("\n")
        except OSError:
            result = {"status": "failed", "reason": "summary: new file could not be written"}
    print(json.dumps(result, indent=2, ensure_ascii=True, allow_nan=False))
    return int(result["status"] != "passed")


if __name__ == "__main__":
    raise SystemExit(main())
