"""Check built distributions without installing third-party validation libraries."""

import argparse
from email.parser import BytesParser
import gzip
import hashlib
import io
from pathlib import Path
import tarfile
import zipfile

from rankprobe import __version__


def check(dist: Path, source: Path) -> None:
    stem = f"rankprobe-{__version__}"
    wheel = dist / f"{stem}-py3-none-any.whl"
    archive = dist / f"{stem}.tar.gz"
    with zipfile.ZipFile(wheel) as package:
        bad = package.testzip()
        if bad:
            raise ValueError(f"wheel CRC check failed: {bad}")
        metadata = BytesParser().parsebytes(package.read(f"{stem}.dist-info/METADATA"))
        if metadata["Version"] != __version__:
            raise ValueError("wheel version differs from source version")
        for requirement in metadata.get_all("Requires-Dist", []):
            if "extra ==" not in requirement:
                raise ValueError(f"unexpected core runtime dependency: {requirement}")
        for module in (source / "src" / "rankprobe").glob("*.py"):
            if package.read(f"rankprobe/{module.name}") != module.read_bytes():
                raise ValueError(f"wheel source differs: {module.name}")
    # Reading through gzip verifies its footer; no archive paths are extracted.
    with gzip.open(archive, "rb") as handle:
        payload = handle.read()
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:") as package:
        names = set(package.getnames())
        expected = {"pyproject.toml", "README.md", "README.zh-CN.md", "MANIFEST.in"}
        for directory in ("examples", "docs", "scripts", "tests", "src/rankprobe"):
            expected.update(
                path.relative_to(source).as_posix()
                for path in (source / directory).rglob("*")
                if path.is_file() and "__pycache__" not in path.parts
            )
        missing = sorted(path for path in expected if f"{stem}/{path}" not in names)
        if missing:
            raise ValueError(f"source distribution missing files: {', '.join(missing)}")
    for path in (wheel, archive):
        print(f"{path.name} sha256={hashlib.sha256(path.read_bytes()).hexdigest()}")
    print("Distribution checks passed: wheel integrity/source/dependencies and source-package files")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, default=Path("dist"))
    arguments = parser.parse_args()
    check(arguments.dist, Path(__file__).resolve().parents[1])


if __name__ == "__main__":
    main()
