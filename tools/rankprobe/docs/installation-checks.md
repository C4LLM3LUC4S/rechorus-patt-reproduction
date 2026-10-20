# Checking the built installation

Source tests and a successful build do not exercise the installed console launcher. An editable development environment can also hide an accidental dependency on development tools or on the checkout. RankProbe therefore uses two separate distribution checks.

```sh
python -m build
python scripts/check_distribution.py
python scripts/check_wheel_install.py --wheel dist/rankprobe-0.1.0a4-py3-none-any.whl
```

Pass an exact wheel path for the version being checked. The checker does not select whichever old artifact happens to be present in `dist`. CI builds in a clean checkout, where its `dist/*.whl` expression resolves to one wheel.

| Check | What is exercised |
| --- | --- |
| Distribution integrity | Wheel CRCs, metadata, packaged source bytes, core dependency declarations, and source-distribution file coverage |
| Fresh installation | A new virtual environment without inherited system packages, created outside the checkout in a path containing spaces |
| Import source | The loaded module belongs to that environment; module, installed-distribution, and wheel versions agree |
| Report implementation | Both reports' core-source identities agree with independently hashed Python files inside the exact wheel |
| Dependencies | Only RankProbe is added beyond the environment's bundled bootstrap tools |
| Entry points | Both isolated `python -I -m rankprobe` and the actual installed `rankprobe` launcher |
| Error recovery | Each installed entry point rejects a late invalid score without output or input changes, accepts a corrected retry at the same paths, and refuses to replace the completed report without explicit overwrite |
| Reports | Built-in demo and copied synthetic TREC inputs produce valid reports; known values, excluded queries, source hashes and matched deltas agree with the fixture |

The installation step uses the existing interpreter's bundled `venv`/`ensurepip` support and installs the specified wheel with `--no-index --no-deps`. It does not upgrade pip or download packages. Build and development dependency installation are separate steps and may need network access. The checker uses a small environment allowlist and excludes source-path overrides. `PIP_CONFIG_FILE` is set to `os.devnull`, which [pip documents as disabling configuration-file loading](https://pip.pypa.io/en/stable/topics/configuration/#pip-config-file).

The local wheel is passed as an escaped file URL with its computed `#sha256=` fragment. Pip checks this fragment, and older bootstrap versions also need it to record the archive hash in `direct_url.json` ([pip secure-install documentation](https://pip.pypa.io/en/stable/topics/secure-installs/), [pip 22.3.1 implementation](https://github.com/pypa/pip/blob/22.3.1/src/pip/_internal/utils/direct_url_helpers.py)). The checker requires the recorded hash to match on all supported Python versions.

To save a compact local result, use a new output filename:

```sh
python scripts/check_wheel_install.py --wheel dist/rankprobe-0.1.0a4-py3-none-any.whl --summary artifacts/wheel-check.json
```

An existing summary is refused. Original wheel and fixture bytes are checked before and after use. Temporary environments, copied inputs and reports are removed after the check; the optional summary contains aggregate checks and the wheel hash. A passing result demonstrates these specific installation flows, not benchmark validity, compatibility with every environment, or external adoption.

The Windows/Ubuntu and Python 3.10/3.12/3.13 matrix runs the full test suite and this gate. A separate Windows/Ubuntu Python 3.15 job installs the core from source without extras, builds the distributions using declared build-tool versions, checks their integrity, and exercises the built wheel in a fresh environment. Its `core-python315-install-Linux` and `core-python315-install-Windows` artifacts contain the interpreter version, wheel hash and aggregate installation checks; parent build tools are not core runtime dependencies.

The Python 3.15 job addresses the newest stable interpreter's core installation path. It does not run the full test suite or establish compatibility for NumPy adapters or native model frameworks. Python 3.14 is not currently in this matrix, and neither check establishes compatibility with every intervening or future interpreter. Inspect the workflow and successful artifacts for the exact commit; an earlier run does not validate a later build.
