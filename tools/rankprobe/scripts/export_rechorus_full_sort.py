"""Export the standard ReChorus GeneralModel full-sort evaluation contract.

This source-checkout helper accepts the complete scores from the same prepared
dev/test Dataset and caller-supplied stable event IDs. It imports optional NumPy,
not ReChorus or Torch. Contract checks do not certify arbitrary model subclasses.
"""

from __future__ import annotations

from collections.abc import Mapping
import csv
import hashlib
import json
from numbers import Integral
from pathlib import Path


def _array(value, np, field: str, *, objects: bool = False):
    try:
        if callable(getattr(value, "detach", None)):
            value = value.detach().cpu().numpy()
        return np.asarray(value, dtype=object if objects else None)
    except (AttributeError, TypeError, ValueError, RuntimeError) as exc:
        raise ValueError(f"{field} cannot be read as an array.") from exc


def _integer(value, field: str, *, minimum: int, maximum: int | None = None) -> int:
    if (isinstance(value, bool) or not isinstance(value, Integral)
            or value < minimum or (maximum is not None and value >= maximum)):
        raise ValueError(f"{field} must contain valid integer IDs.")
    return int(value)


def _integer_vector(value, np, field: str, count: int, *, minimum: int,
                    maximum: int | None = None) -> list[int]:
    array = _array(value, np, field, objects=True)
    if array.ndim != 1 or len(array) != count:
        raise ValueError(f"{field} must be a vector matching every source row or column.")
    return [_integer(item, field, minimum=minimum, maximum=maximum) for item in array.tolist()]


def _event_ids(value, np, count: int) -> list[str]:
    array = _array(value, np, "query_ids", objects=True)
    if array.ndim != 1 or len(array) != count:
        raise ValueError("query_ids must be a vector matching every source score row.")
    result = []
    for token in array.tolist():
        if isinstance(token, bytes):
            try:
                token = token.decode("utf-8", errors="strict")
            except UnicodeError as exc:
                raise ValueError("query_ids must contain valid UTF-8 strings.") from exc
        if not isinstance(token, str) or not token.strip():
            raise ValueError("query_ids must contain nonempty string event IDs.")
        if len(token) > 4096:
            raise ValueError("query_ids exceed the 4096-character input limit.")
        try:
            token.encode("utf-8", errors="strict")
        except UnicodeError as exc:
            raise ValueError("query_ids must contain valid UTF-8 strings.") from exc
        result.append(token)
    if len(set(result)) != len(result):
        raise ValueError("query_ids must be unique event IDs, not repeated user IDs.")
    return result


def _clicked_items(table, user: int, item_num: int, field: str) -> frozenset[int]:
    if not isinstance(table, Mapping) or user not in table:
        raise ValueError(f"{field} is unavailable for a source user.")
    items = table[user]
    if not isinstance(items, (set, frozenset)):
        raise ValueError(f"{field} must provide item-ID sets as in the standard reader.")
    return frozenset(_integer(item, field, minimum=1, maximum=item_num) for item in items)


def _new_directory(path: Path) -> Path:
    path = Path(path).absolute()
    if path.exists() or path.is_symlink():
        raise ValueError("Output directory must be new; existing output is never overwritten.")
    if any(parent.is_symlink() for parent in path.parents):
        raise ValueError("Output directory must not have symbolic-link ancestors.")
    if not path.parent.is_dir():
        raise ValueError("Output parent directory must already exist.")
    return path


def export_full_sort(scores, dataset, query_ids, output_directory: Path) -> dict:
    """Write finite predictions and explicit catalog exclusions to a new directory.

    Scope: standard ``GeneralModel.Dataset``, phase dev/test, ``test_all=1``.
    Individual feed rows must have exactly user_id/item_id and candidate columns
    ``[observed_target, 1, ..., corpus.n_items - 1]``. Column zero is the observed
    positive, not padding. Its duplicate in the catalog must already belong to
    the native train/residual mask, which this helper verifies rather than adds.

    Residual clicked sets include dev/test interactions; they are not necessarily
    causal history. Exclusion reasons can overlap. Unknown relevance stays blank.
    The caller must establish exact score-row order and stable event/item meaning.
    Validation finishes before writes; a later filesystem error may leave partial
    files in the new directory. Existing files are never replaced.
    """
    out = _new_directory(output_directory)
    try:
        import numpy as np
    except ImportError as exc:
        raise ValueError(
            'This optional exporter needs NumPy: pip install -e ".[adapters]"'
        ) from exc

    if getattr(dataset, "phase", None) not in {"dev", "test"}:
        raise ValueError("Only standard GeneralModel dev/test full-sort datasets are supported.")
    flag = getattr(getattr(dataset, "model", None), "test_all", None)
    if not (flag is True or (isinstance(flag, Integral) and not isinstance(flag, bool) and flag == 1)):
        raise ValueError("Dataset model.test_all must be the explicit full-sort flag 1 or True.")
    corpus = getattr(dataset, "corpus", None)
    item_num = _integer(getattr(corpus, "n_items", None), "corpus.n_items", minimum=2)
    user_num = getattr(corpus, "n_users", None)
    if user_num is not None:
        user_num = _integer(user_num, "corpus.n_users", minimum=1)
    try:
        row_count = len(dataset)
    except (TypeError, ValueError) as exc:
        raise ValueError("Dataset length is unavailable.") from exc
    if row_count < 1:
        raise ValueError("Dataset must contain at least one prediction context.")
    values = _array(scores, np, "scores")
    if values.ndim != 2 or values.shape != (row_count, item_num):
        raise ValueError("scores shape must be exactly (len(dataset), corpus.n_items).")
    if values.dtype.kind != "f" or values.dtype.itemsize > 8:
        raise ValueError("scores must use real floating-point values of at most 64 bits.")
    events = _event_ids(query_ids, np, row_count)
    data = getattr(dataset, "data", None)
    if not isinstance(data, Mapping) or not {"user_id", "item_id"}.issubset(data):
        raise ValueError("Dataset must declare source user_id and item_id rows.")
    users = _integer_vector(data["user_id"], np, "source user_id", row_count,
                            minimum=0, maximum=user_num)
    targets = _integer_vector(data["item_id"], np, "source target item_id", row_count,
                              minimum=1, maximum=item_num)
    train_table = getattr(corpus, "train_clicked_set", None)
    residual_table = getattr(corpus, "residual_clicked_set", None)
    native_masks = {}
    queries = []
    reason_counts = {"train_clicked": 0, "residual_clicked": 0, "own_target_catalog_duplicate": 0}
    excluded_count = 0
    for row_index, (user, target, event) in enumerate(zip(users, targets, events)):
        try:
            feed = dataset[row_index]
        except (IndexError, KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"Dataset feed row {row_index} is unavailable.") from exc
        if not isinstance(feed, Mapping) or set(feed) != {"user_id", "item_id"}:
            raise ValueError("Only standard feed rows with exactly user_id/item_id are supported.")
        if _integer(feed["user_id"], "feed user_id", minimum=0, maximum=user_num) != user:
            raise ValueError(f"Dataset user row alignment differs at score row {row_index}.")
        candidates = _integer_vector(feed["item_id"], np, "feed item_id", item_num,
                                     minimum=1, maximum=item_num)
        if candidates[0] != target or candidates[1:] != list(range(1, item_num)):
            raise ValueError(f"Dataset candidate columns must be [target, 1..n_items-1] at row {row_index}.")
        if user not in native_masks:
            train = _clicked_items(train_table, user, item_num, "train_clicked_set")
            residual = _clicked_items(residual_table, user, item_num, "residual_clicked_set")
            native_masks[user] = (train, residual, train | residual)
        train, residual, excluded = native_masks[user]
        if target not in excluded:
            raise ValueError(f"Observed target catalog duplicate is absent from the native mask at row {row_index}.")
        if not np.isfinite(values[row_index, 0]):
            raise ValueError(f"Column zero observed positive score must be finite at row {row_index}.")
        mask = np.zeros(item_num, dtype=bool)
        mask[list(excluded)] = True
        if not np.isneginf(values[row_index, mask]).all():
            raise ValueError(f"Declared catalog masks must be -inf at score row {row_index}.")
        if not np.isfinite(values[row_index, ~mask]).all():
            raise ValueError(f"Eligible scores must be finite at score row {row_index}.")
        exclusions = []
        for item in sorted(excluded):
            reasons = []
            if item in train:
                reasons.append("train_clicked")
            if item in residual:
                reasons.append("residual_clicked")
            if item == target:
                reasons.append("own_target_catalog_duplicate")
            for reason in reasons:
                reason_counts[reason] += 1
            exclusions.append({"column_index": item, "item_id": str(item), "reasons": reasons})
        queries.append({"row_index": row_index, "query_id": event,
                        "observed_target_item_id": str(target),
                        "exported_rows": item_num - len(excluded), "exclusions": exclusions})
        excluded_count += len(excluded)

    exported_count = row_count * item_num - excluded_count
    result = {
        "schema_version": 1, "scope": "rechorus_generalmodel_full_sort",
        "dataset_phase": dataset.phase, "query_count": row_count,
        "candidate_columns": item_num, "exported_rows": exported_count,
        "observed_positive_rows": row_count, "unknown_rows": exported_count - row_count,
        "excluded_rows": excluded_count, "exclusions_by_reason": reason_counts,
        "exclusion_count_note": "Reasons overlap; excluded_rows counts unique masked positions, not the sum of reason counts.",
        "queries": queries, "declared_positive_column": 0,
        "label_policy": "column_zero_observed_target_positive; other_eligible_candidates_unknown",
        "other_candidates": "unknown", "qrels_complete": False,
        "identity_mode": "source", "retained_source_ids": True,
        "query_identity": "caller-supplied stable event IDs; repeated users remain separate contexts",
        "item_identity": "native integer item IDs retained as exact decimal strings",
        "caller_alignment": "Caller must establish exact score-row order and shared event/item meaning; contract checks cannot certify alignment.",
        "user_ids_exported": None, "user_id_array_exported": False,
        "score_representation": "round-trip binary64 decimal",
        "candidate_policy_note": "Native train/residual catalog union; residual includes dev/test interactions, not necessarily causal history or a leakage certificate.",
        "privacy_note": "Source event/item IDs are retained and may identify people; anonymity and redistribution rights are not established.",
    }
    out.mkdir()
    prediction_path = out / "predictions.csv"
    with prediction_path.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(("query_id", "item_id", "score", "relevance"))
        for row_index, (user, target, event) in enumerate(zip(users, targets, events)):
            excluded = native_masks[user][2]
            writer.writerow((event, str(target), repr(float(values[row_index, 0])), "1"))
            for item in range(1, item_num):
                if item not in excluded:
                    writer.writerow((event, str(item), repr(float(values[row_index, item])), ""))
    checksum = hashlib.sha256()
    with prediction_path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            checksum.update(block)
    result["predictions_sha256"] = checksum.hexdigest()
    with (out / "exclusions.json").open("x", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")
    return result
