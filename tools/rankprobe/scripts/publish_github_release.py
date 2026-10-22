"""Publish checked assets through the official gh CLI, explicitly and without replacement."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile


REPOSITORY = "C4LLM3LUC4S/rechorus-patt-reproduction"


def gh(*arguments, check=True):
    return subprocess.run(["gh", *arguments], check=check, capture_output=True, text=True)


def find_release(tag):
    releases = json.loads(gh("api", f"repos/{REPOSITORY}/releases?per_page=100").stdout)
    matches = [release for release in releases if release["tag_name"] == tag]
    if len(matches) > 1:
        raise ValueError("Multiple releases use this tag")
    return matches[0] if matches else None


def publish(assets, notes, allow_publish=False):
    info = json.loads((assets / "RELEASE_INFO.json").read_text(encoding="utf-8"))
    version, commit = info["version"], info["source_commit"]
    if info["repository"] != REPOSITORY or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("Unexpected repository or source identity")
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:a\d+|b\d+|rc\d+)?", version):
        raise ValueError("Unexpected version")
    expected = {}
    for line in (assets / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        digest, name = line.split("  ", 1)
        if (name in expected or Path(name).name != name or "/" in name or "\\" in name
                or not re.fullmatch(r"[0-9a-f]{64}", digest)):
            raise ValueError("Unsafe or duplicate checksum entry")
        if hashlib.sha256((assets / name).read_bytes()).hexdigest() != digest:
            raise ValueError(f"Local checksum mismatch: {name}")
        expected[name] = digest
    if set(path.name for path in assets.iterdir()) != set(expected) | {"SHA256SUMS"}:
        raise ValueError("Release asset list differs from checksums")
    if set(expected) != {"RELEASE_INFO.json", f"RankProbe-{version}.zip",
                         f"rankprobe-{version}-py3-none-any.whl", f"rankprobe-{version}.tar.gz"}:
        raise ValueError("Unexpected release asset names")
    expected["SHA256SUMS"] = hashlib.sha256((assets / "SHA256SUMS").read_bytes()).hexdigest()
    tag = "v" + version
    if not allow_publish:
        print(json.dumps({"operation": "dry_run", "tag": tag, "commit": commit,
                          "assets": sorted(expected), "network_or_mutation": False}))
        return
    local_commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=notes.parent).decode().strip()
    if local_commit != commit:
        raise ValueError("Release assets do not match the checked-out commit")
    endpoint = f"repos/{REPOSITORY}/releases/tags/{tag}"
    release = find_release(tag)
    if release is not None and release.get("target_commitish") != commit:
        if release.get("draft"):
            raise ValueError("This draft already has another source identity; inspect it before retrying")
        print(json.dumps({"status": "already_released", "tag": tag,
                          "source_commit": release["target_commitish"],
                          "url": release["html_url"], "new_publication": False,
                          "next": "Bump the version and add matching notes to publish another snapshot"}))
        return
    if release is None:
        ref = gh("api", f"repos/{REPOSITORY}/git/ref/tags/{tag}", check=False)
        if ref.returncode == 0:
            obj = json.loads(ref.stdout)["object"]
            if obj["type"] != "commit" or obj["sha"] != commit:
                raise ValueError("Existing tag identifies another source; no write attempted")
        elif "404" not in ref.stderr:
            raise RuntimeError("Could not check the tag; no write attempted")
        with tempfile.TemporaryDirectory(prefix="rankprobe-release-notes-") as temporary:
            body = Path(temporary) / "notes.md"
            body.write_text(notes.read_text(encoding="utf-8") +
                            f"\n\nSource commit: `{commit}`.\n\nCI: {info['ci_url']}\n", encoding="utf-8")
            arguments = ["release", "create", tag, "--repo", REPOSITORY,
                         "--target", commit, "--title", f"RankProbe {version}",
                         "--notes-file", str(body), "--draft"]
            if any(marker in version for marker in ("a", "b", "rc")):
                arguments.append("--prerelease")
            gh(*arguments, *(str(assets / name) for name in sorted(expected)))
        release = find_release(tag)
    actual = {asset["name"] for asset in release["assets"]}
    if release["draft"] and actual < set(expected):
        gh("release", "upload", tag, "--repo", REPOSITORY,
           *(str(assets / name) for name in sorted(set(expected) - actual)))
        release = find_release(tag)
    if {asset["name"] for asset in release["assets"]} != set(expected):
        raise ValueError("Remote asset names differ; release left unchanged")
    with tempfile.TemporaryDirectory(prefix="rankprobe-release-download-") as temporary:
        gh("release", "download", tag, "--repo", REPOSITORY, "--dir", temporary)
        for name, digest in expected.items():
            if hashlib.sha256((Path(temporary) / name).read_bytes()).hexdigest() != digest:
                raise ValueError(f"Downloaded release asset mismatch: {name}")
    if release["draft"]:
        gh("release", "edit", tag, "--repo", REPOSITORY, "--draft=false")
    published = json.loads(gh("api", endpoint).stdout)
    if published["draft"] or published["target_commitish"] != commit:
        raise ValueError("Publication state differs from the requested release")
    tagged = json.loads(gh("api", f"repos/{REPOSITORY}/git/ref/tags/{tag}").stdout)
    if tagged["object"]["type"] != "commit" or tagged["object"]["sha"] != commit:
        raise ValueError("Published tag does not identify the accepted commit")
    print(json.dumps({"status": "published", "tag": tag, "source_commit": commit,
                      "url": published["html_url"], "assets_verified": len(expected),
                      "prerelease": published["prerelease"]}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--notes", type=Path, required=True)
    parser.add_argument("--publish", action="store_true")
    arguments = parser.parse_args()
    publish(arguments.assets.resolve(), arguments.notes.resolve(), arguments.publish)


if __name__ == "__main__":
    main()
