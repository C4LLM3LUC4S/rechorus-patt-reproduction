# Keep reports when a local evaluation check fails

A findings failure is useful only if you can inspect its report. RankProbe writes both reports before returning `1` for findings; invalid input or an output error returns `2`. A caller that stops immediately on a nonzero status can skip its later artifact-collection step. In a Python job, [Python documents that `subprocess.run(..., check=True)` raises](https://docs.python.org/3/library/subprocess.html#subprocess.run) before that later code runs when a findings check returns `1`. Catch that expected status or use `check=False` and handle the result explicitly.

This small project template audits one export or compares two exports. It uses the core interpreter already selected in the [first-report setup](try-it.md#1-install-locally), preserves the CLI status, and lists local artifacts after a completed run. Save the following as `local_rankprobe_check.py`. It uses only the standard library and your installed RankProbe; it is not a new RankProbe command.

This status handling applies to RankProbe. First require any upstream exporter or converter to succeed under its own contract and check its expected query-item coverage. A failed conversion can leave a parseable prefix; passing that file to RankProbe cannot establish export completion. The [executed converter handoff control](../examples/score-provenance/README.md#check-conversion-completion-before-auditing-its-output) demonstrates failure, rejection of incomplete coverage and a corrected fresh-output retry.

```python
import argparse
from pathlib import Path
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description="Run a local RankProbe check and retain its reports.")
    parser.add_argument("inputs", nargs="+", type=Path, metavar="FILE")
    parser.add_argument("--qrels", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--fail-on", choices=("error", "warning"), default="warning")
    args = parser.parse_args()
    if len(args.inputs) not in (1, 2):
        parser.error("supply one prediction file to audit or two files to compare")
    if args.out.exists() or args.out.is_symlink():
        print("Runner error: --out already exists. Choose a new directory; old reports were not read.",
              file=sys.stderr)
        return 2

    output = args.out.absolute()
    inputs = [str(path.absolute()) for path in args.inputs]
    command = [sys.executable, "-m", "rankprobe"]
    if len(inputs) == 1:
        command += ["audit", inputs[0]]
    else:
        command += ["compare", "--run", "baseline=" + inputs[0],
                    "--run", "candidate=" + inputs[1]]
    if args.qrels is not None:
        command += ["--qrels", str(args.qrels.absolute())]
    command += ["--fail-on", args.fail_on, "--out", str(output)]
    try:
        result = subprocess.run(command, shell=False, check=False)
    except OSError:
        print("Runner error: could not start the core interpreter.", file=sys.stderr)
        return 2

    if result.returncode in (0, 1):
        reports = [output / "report.json", output / "report.html"]
        if not all(path.is_file() for path in reports):
            print("Runner error: completed CLI status without both report files; nothing collected.",
                  file=sys.stderr)
            return 2
        for path in reports:
            message = f"Local artifact: {path}"
            encoding = sys.stdout.encoding or "utf-8"
            print(message.encode(encoding, errors="backslashreplace").decode(encoding))
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
```

The `Local artifact` branch is where a project can invoke its approved local artifact collector before returning the status; the example only lists the retained files. Host CI retention still needs the configuration described below.

The template accepts the CLI's automatically detected formats: prediction `.csv`, `.jsonl`, `.run` or `.trec`, and qrels `.csv`, `.jsonl` or `.qrels`. Other CLI options, including explicit formats for `.txt`, can be added to this project's argument list after reviewing the [input contract](input-format.md). It retains the CLI's default cutoffs and unknown-label policy; it makes no completeness assertion. Two inputs are named `baseline` and `candidate` in the comparison.

From the package folder, use a new output name each time. Activation is unnecessary. For example, with your permitted files in `my exports`:

Windows PowerShell:

```powershell
.\.venv\Scripts\python.exe local_rankprobe_check.py "my exports/predictions.csv" --out "local CI reports/run-001"
.\.venv\Scripts\python.exe local_rankprobe_check.py "my exports/baseline.run" "my exports/candidate.run" --qrels "my exports/judgments.qrels" --out "local CI reports/run-002"
```

macOS / Linux:

```sh
.venv/bin/python local_rankprobe_check.py "my exports/predictions.csv" --out "local CI reports/run-001"
.venv/bin/python local_rankprobe_check.py "my exports/baseline.run" "my exports/candidate.run" --qrels "my exports/judgments.qrels" --out "local CI reports/run-002"
```

The subprocess uses this same interpreter and an argument list, so spaces in paths and comparison names are not interpreted by a shell. On a console that cannot encode a path, the artifact message escapes that text; the actual filenames are unchanged.

For normal completed runs, statuses `0` and `1` are returned unchanged after checking that both report files exist. The runner does not parse or print their contents. Status `1` covers warning findings under this template's default policy and error findings; use JSON finding `code` and `severity` to distinguish them. Status `2` collects no report; an output error may leave partial files, which are not a completed report pair. The runner also returns `2` if its output preflight or report-pair check fails; those are runner/output errors, not completed findings. It never reads a previous report, overwrites an output, deletes files or uploads anything.

Configure your host CI's artifact-collection step to run even when this command fails. Retain the report pair from this invocation's fresh output directory, while keeping its original failure status. A normal success-only later step may be skipped after status `1`. For a local parent script, handle that collection before returning the status. Review IDs and examples before sharing: a retained report may contain private or licensed data and should not be published automatically.

An exit `0` only means no finding met the selected threshold. For example, changing to `--fail-on error` permits warnings and can leave some metrics unavailable. Inspect schema version `0.1`, structured finding codes, each metric's status, eligible-query coverage and reference scope. A partial value or missing metric is not zero and is not a model-quality certificate. This template adds no metric threshold or automatic repair policy.
