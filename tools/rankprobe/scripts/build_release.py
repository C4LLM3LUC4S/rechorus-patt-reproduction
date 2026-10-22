"""Build a curated offline release from committed RankProbe source only."""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import zipfile

from check_distribution import check


ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "C4LLM3LUC4S/rechorus-patt-reproduction"
ALLOWED_ROOT_FILES = {
    ".gitattributes", ".gitignore", "CHANGELOG.md", "CITATION.cff",
    "CONTRIBUTING.md", "LICENSE", "MANIFEST.in", "README.md",
    "README.zh-CN.md", "pyproject.toml",
}
ALLOWED_DIRECTORIES = {".github", "docs", "examples", "scripts", "src", "tests"}
ALLOWED_SUFFIXES = {".md", ".py", ".txt", ".csv", ".jsonl", ".run", ".trec", ".qrels", ".tsv", ".yml"}


def git(*arguments):
    return subprocess.check_output(["git", *arguments], cwd=ROOT)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def json_bytes(value):
    return (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode()


def committed_source():
    top = Path(git("rev-parse", "--show-toplevel").decode().strip()).resolve()
    prefix = ROOT.relative_to(top).as_posix()
    prefix = "" if prefix == "." else prefix + "/"
    scope = prefix.rstrip("/") or "."
    if git("status", "--porcelain", "--untracked-files=no", "--", ".").strip():
        raise ValueError("Commit tracked package changes before building a release")
    members = {}
    listing = git("ls-tree", "-rz", "--full-tree", "HEAD", "--", scope)
    for entry in listing.split(b"\0"):
        if not entry:
            continue
        header, raw_path = entry.split(b"\t", 1)
        mode, kind, sha = header.decode().split()
        name = raw_path.decode("utf-8")
        if not name.startswith(prefix):
            raise ValueError("Source is outside the package")
        relative = PurePosixPath(name[len(prefix):])
        if mode not in {"100644", "100755"} or kind != "blob":
            raise ValueError(f"Non-regular source entry: {relative}")
        if relative.is_absolute() or ".." in relative.parts or "\\" in str(relative):
            raise ValueError("Unsafe source path")
        if len(relative.parts) == 1:
            allowed = str(relative) in ALLOWED_ROOT_FILES
        else:
            allowed = relative.parts[0] in ALLOWED_DIRECTORIES and relative.suffix in ALLOWED_SUFFIXES
        if not allowed:
            raise ValueError(f"Review unapproved release source: {relative}")
        members["source/" + relative.as_posix()] = git("cat-file", "blob", sha)
    if "source/LICENSE" not in members or "source/src/rankprobe/cli.py" not in members:
        raise ValueError("Required source or license is absent")
    return members, prefix.rstrip("/"), git("rev-parse", "HEAD").decode().strip()


def build(distributions, output, ci_url=None):
    members, source_path, commit = committed_source()
    version = re.search(r'^version = "([^"]+)"$', members["source/pyproject.toml"].decode(), re.M)[1]
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:a\d+|b\d+|rc\d+)?", version):
        raise ValueError("Unsupported release version")
    if ci_url is not None and not re.fullmatch(
        rf"https://github.com/{re.escape(REPOSITORY)}/actions/runs/\d+", ci_url
    ):
        raise ValueError("Unexpected CI receipt URL")
    names = [f"rankprobe-{version}-py3-none-any.whl", f"rankprobe-{version}.tar.gz"]
    if {path.name for path in distributions.iterdir()} != set(names):
        raise ValueError("Distribution folder must contain exactly this version's wheel and sdist")
    check(distributions, ROOT)
    output.mkdir(parents=True, exist_ok=False)
    for name in names:
        payload = (distributions / name).read_bytes()
        members["dist/" + name] = payload
        shutil.copyfile(distributions / name, output / name)
    info = {
        "schema_version": 1, "project": "RankProbe", "version": version,
        "repository": REPOSITORY, "source_commit": commit, "source_path": source_path,
        "ci_url": ci_url,
        "scope": "Curated RankProbe source, original fixtures and dependency-free core distributions; no user records or third-party datasets",
    }
    members["BUILD_INFO.json"] = json_bytes(info)
    members["START_HERE.md"] = f"""# RankProbe {version} / 从这里开始

Python 3.10+ is required. Extract this entire ZIP into a short, fresh path.
需要 Python 3.10 或以上。请完整解压到较短的新路径，在本文件所在目录打开终端。

Windows PowerShell (no activation or network required / 无需激活环境或联网):

```powershell
python -m venv .venv
.\\.venv\\Scripts\\python.exe -m pip install --no-index --no-deps .\\dist\\{names[0]}
.\\.venv\\Scripts\\python.exe -I -m rankprobe --version
.\\.venv\\Scripts\\python.exe -I -m rankprobe demo --out reports/demo
Start-Process .\\reports\\demo\\report.html
```

macOS / Linux:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install --no-index --no-deps dist/{names[0]}
.venv/bin/python -I -m rankprobe demo --out reports/demo
```

Open `reports/demo/report.html` in a browser. No API key, model or dataset is needed.
浏览器打开报告即可，无需密钥、训练模型或下载数据。已有报告不会被静默覆盖。

For the full comparison walkthrough, open [source/docs/try-it.md](source/docs/try-it.md).
Its fixture paths are relative to `source/`; run `cd source` first and use the
environment interpreter one directory above (`..\\.venv\\Scripts\\python.exe`
on Windows, `../.venv/bin/python` on macOS/Linux).

[中文说明](source/README.zh-CN.md) · [Input contract](source/docs/input-format.md)
· [Limitations](source/docs/limitations.md) · [MIT license](source/LICENSE)

Missing judgments remain unknown. A finding or a matching metric is not a model-quality certificate.
未标注不等于零分；报告用于定位和解释评测问题，不认证模型质量。

`BUILD_INFO.json` records the exact public commit. `MANIFEST.json` hashes every
other member. The release's `SHA256SUMS` verifies the downloaded ZIP and packages.
""".encode("utf-8")
    members["MANIFEST.json"] = json_bytes({
        "schema_version": 1, "source_commit": commit,
        "files": {name: {"sha256": digest(data), "bytes": len(data)}
                  for name, data in sorted(members.items())},
    })
    bundle = output / f"RankProbe-{version}.zip"
    with zipfile.ZipFile(bundle, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in sorted(members.items()):
            entry = zipfile.ZipInfo(name, date_time=(2026, 10, 22, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = 0o100644 << 16
            archive.writestr(entry, data)
    with zipfile.ZipFile(bundle) as archive:
        if archive.testzip() or len(archive.namelist()) != len(set(archive.namelist())):
            raise ValueError("Invalid bundle")
        manifest = json.loads(archive.read("MANIFEST.json"))
        if set(archive.namelist()) != set(manifest["files"]) | {"MANIFEST.json"}:
            raise ValueError("Manifest does not cover the bundle")
        for name, expected in manifest["files"].items():
            data = archive.read(name)
            if len(data) != expected["bytes"] or digest(data) != expected["sha256"]:
                raise ValueError(f"Bundle identity mismatch: {name}")
    info["assets"] = {path.name: {"bytes": path.stat().st_size, "sha256": digest(path.read_bytes())}
                      for path in sorted(output.iterdir())}
    (output / "RELEASE_INFO.json").write_bytes(json_bytes(info))
    sums = "".join(f"{digest(path.read_bytes())}  {path.name}\n" for path in sorted(output.iterdir()))
    (output / "SHA256SUMS").write_text(sums, encoding="utf-8", newline="\n")
    print(json.dumps({"version": version, "source_commit": commit,
                      "source_files": len([name for name in members if name.startswith('source/')]),
                      "bundle_members": len(members), "release_assets": len(list(output.iterdir()))}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, default=ROOT / "dist")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--ci-url")
    arguments = parser.parse_args()
    build(arguments.dist.resolve(), arguments.out.resolve(), arguments.ci_url)


if __name__ == "__main__":
    main()
