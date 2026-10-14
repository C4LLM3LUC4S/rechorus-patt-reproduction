# Contributing

RankProbe is an early alpha. A useful first contribution is a small, shareable
prediction file that exposes a confusing diagnostic, installation failure or
evaluation assumption we have missed.

Please provide the command, Python/OS versions, expected behavior, and a minimal
synthetic reproduction. Keep private queries, documents, identifiers, and
licensed datasets out of public issues and pull requests. An anonymized ID alone
does not establish permission to share a dataset.

Run `python -m pytest` and `python -m ruff check .` after installing `.[dev]`.
Numerical changes need an independent hand calculation, known reference, or
exhaustive small example; tests that repeat the implementation are not sufficient.
Protocol changes must update the input/metric documentation and evidence in the
report. Never describe unknown judgments as nonrelevant without an explicit
protocol assumption.

Keep the core standard-library-only. NumPy belongs to optional export adapters.
Large features should first demonstrate a real user need with a minimal case.
