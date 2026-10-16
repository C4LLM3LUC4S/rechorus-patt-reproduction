"""RankProbe: inspect ranking evaluation assumptions and their numerical effects."""

from .model import Protocol, Row
from .audit import audit_run, compare_runs
from .metrics import evaluate_metrics

__version__ = "0.1.0a4"
__all__ = ["Protocol", "Row", "audit_run", "compare_runs", "evaluate_metrics", "__version__"]
