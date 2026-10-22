"""Public input and protocol contracts. No model-training dependencies."""

from dataclasses import dataclass
import math


def _unicode_text(value: str, field: str) -> None:
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError(f"{field} must contain valid Unicode text") from exc


def _identifier(value: str, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    if len(value) > 4096:
        raise ValueError(f"{field} exceeds the 4096-character input limit")
    _unicode_text(value, field)


def _number(value: float, field: str, *, nonnegative: bool = False) -> None:
    try:
        finite = isinstance(value, (int, float)) and math.isfinite(value)
    except (OverflowError, TypeError, ValueError):
        finite = False
    if isinstance(value, bool) or not finite:
        raise ValueError(f"{field} must be a finite number (Python int or float)")
    if nonnegative and value < 0:
        raise ValueError(f"{field} must be non-negative")


@dataclass(frozen=True)
class Row:
    query_id: str
    item_id: str
    score: float
    relevance: float | None = None

    def __post_init__(self) -> None:
        _identifier(self.query_id, "query_id")
        _identifier(self.item_id, "item_id")
        _number(self.score, "score")
        if self.relevance is not None:
            _number(self.relevance, "relevance", nonnegative=True)


@dataclass(frozen=True)
class Protocol:
    cutoffs: tuple[int, ...] = (1, 5, 10)
    tie_policy: str = "item_id"
    gain: str = "linear"
    relevance_threshold: float = 0.0
    unjudged: str = "unknown"
    qrels_complete: bool = False
    duplicate_policy: str = "max_score"

    def __post_init__(self) -> None:
        try:
            cutoffs = tuple(self.cutoffs)
        except TypeError as exc:
            raise ValueError("cutoffs must be a non-empty sequence of positive integers") from exc
        if not cutoffs or any(
            isinstance(k, bool) or not isinstance(k, int) or k < 1 for k in cutoffs
        ):
            raise ValueError("cutoffs must be a non-empty sequence of positive integers")
        object.__setattr__(self, "cutoffs", tuple(sorted(set(cutoffs))))
        if self.tie_policy not in {"item_id", "input"}:
            raise ValueError("tie_policy must be 'item_id' or 'input'")
        if self.gain not in {"linear", "exp2"}:
            raise ValueError("gain must be 'linear' or 'exp2'")
        if self.unjudged not in {"unknown", "nonrelevant"}:
            raise ValueError("unjudged must be 'unknown' or 'nonrelevant'")
        if self.duplicate_policy != "max_score":
            raise ValueError("duplicate_policy must be 'max_score'")
        _number(self.relevance_threshold, "relevance_threshold", nonnegative=True)
        if not isinstance(self.qrels_complete, bool):
            raise ValueError("qrels_complete must be a boolean")
