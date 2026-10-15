"""Export nonsequential RecBole full-sort scores with explicit mask reasons.

Use this source-checkout helper after ``full_sort_scores``. It does not train a
model, infer judgments, or accept sequential recommendation contexts. NumPy is
optional; neither RecBole nor Torch is imported by this module.
"""

from __future__ import annotations

import csv
import hashlib
import json
from numbers import Integral
from pathlib import Path


def _array(value, np, field: str):
    """Read NumPy arrays or detached CPU tensor values without changing them."""
    try:
        if callable(getattr(value, "detach", None)):
            value = value.detach().cpu().numpy()
        return np.asarray(value)
    except (AttributeError, TypeError, ValueError, RuntimeError) as exc:
        raise ValueError(f"{field} cannot be read as a numeric array.") from exc


def _tokens(dataset, field: str, internal_ids, np, label: str) -> list[str]:
    try:
        values = np.asarray(dataset.id2token(field, internal_ids.copy()))
    except (AttributeError, IndexError, KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"{label} external tokens cannot be resolved.") from exc
    if values.ndim != 1 or len(values) != len(internal_ids):
        raise ValueError(f"{label} token mapping must preserve the supplied ID order and shape.")
    result = values.tolist()
    if any(not isinstance(value, str) or not value.strip() for value in result):
        raise ValueError(f"{label} external tokens must be nonempty strings.")
    if any(len(value) > 4096 for value in result):
        raise ValueError(f"{label} external tokens exceed the 4096-character input limit.")
    try:
        for value in result:
            value.encode("utf-8")
    except UnicodeError as exc:
        raise ValueError(f"{label} external tokens must be valid UTF-8 text.") from exc
    if len(set(result)) != len(result):
        raise ValueError(f"{label} external tokens must be unique.")
    return result


def _new_directory(path: Path) -> Path:
    path = Path(path).absolute()
    if path.exists() or path.is_symlink():
        raise ValueError("Output directory must be new; existing output is never overwritten.")
    if any(parent.is_symlink() for parent in path.parents):
        raise ValueError("Output directory must not have symbolic-link ancestors.")
    if not path.parent.is_dir():
        raise ValueError("Output parent directory must already exist.")
    return path


def export_full_sort(scores, uid_series, test_data, output_directory: Path) -> dict:
    """Write prediction CSV and mask metadata for one declared user order.

    ``scores`` must be the complete two-dimensional output of RecBole's
    ``full_sort_scores`` for the exact same ``uid_series`` and ``test_data``.
    The caller owns that alignment assertion. External tokens are retained,
    including in exclusion metadata; this is not anonymization.

    Only padding and the loader's declared history positions are excluded,
    and each must carry the expected negative-infinity mask. Every eligible
    score must be finite. Missing judgments remain absent: supply a separate
    qrels file to RankProbe when judgments are available.

    All validation finishes before any directory or file is created. A later
    filesystem error can leave partial files in the newly created directory;
    the helper never reuses that directory or replaces an existing file.
    """
    out = _new_directory(output_directory)
    try:
        import numpy as np
    except ImportError as exc:
        raise ValueError(
            'This optional exporter needs NumPy: pip install -e ".[adapters]"'
        ) from exc

    if getattr(test_data, "is_sequential", None) is not False:
        raise ValueError("Only nonsequential full-sort evaluation is supported.")
    dataset = getattr(test_data, "dataset", None)
    item_num = getattr(dataset, "item_num", None)
    user_num = getattr(dataset, "user_num", None)
    if (isinstance(item_num, bool) or not isinstance(item_num, Integral) or item_num < 2
            or isinstance(user_num, bool) or not isinstance(user_num, Integral) or user_num < 2):
        raise ValueError("Dataset user_num and item_num must include padding and real IDs.")
    uid_field, iid_field = getattr(dataset, "uid_field", None), getattr(dataset, "iid_field", None)
    if not isinstance(uid_field, str) or not isinstance(iid_field, str):
        raise ValueError("Dataset must declare uid_field and iid_field.")

    users = _array(uid_series, np, "uid_series")
    if (users.ndim != 1 or users.size == 0 or users.dtype.kind not in "iu"
            or np.any(users < 1) or np.any(users >= user_num)):
        raise ValueError("uid_series must be a nonempty vector of valid positive integer IDs.")
    if len(np.unique(users)) != len(users):
        raise ValueError("uid_series must contain unique users; contexts must not be merged.")
    values = _array(scores, np, "scores")
    if values.ndim != 2 or values.shape != (len(users), item_num):
        raise ValueError("scores shape must be exactly (len(uid_series), dataset.item_num).")
    if values.dtype.kind != "f" or values.dtype.itemsize > 8:
        raise ValueError("scores must use real floating-point values of at most 64 bits.")

    query_tokens = _tokens(dataset, uid_field, users, np, "User")
    item_tokens = _tokens(dataset, iid_field, np.arange(item_num), np, "Item")
    history_table = getattr(test_data, "uid2history_item", None)
    queries = []
    excluded_items = []
    history_count = 0
    exported_count = 0
    for row_index, (uid, query_id) in enumerate(zip(users, query_tokens)):
        try:
            history = history_table[int(uid)]
        except (IndexError, KeyError, TypeError) as exc:
            raise ValueError(f"History is unavailable for score row {row_index}.") from exc
        if history is None:
            raise ValueError(f"History is unavailable for score row {row_index}.")
        history = _array(history, np, "history")
        if history.ndim != 1 or (history.size and (
                history.dtype.kind not in "iu"
                or np.any(history < 0) or np.any(history >= item_num))):
            raise ValueError(f"History contains invalid item IDs at score row {row_index}.")
        if len(np.unique(history)) != len(history):
            raise ValueError(f"History contains duplicate item IDs at score row {row_index}.")
        # Padding is always counted once, even if the loader also declares it as history.
        history_items = sorted(int(item) for item in history if item != 0)
        excluded = [0, *history_items]
        mask = np.zeros(item_num, dtype=bool)
        mask[excluded] = True
        if not np.isneginf(values[row_index, mask]).all():
            raise ValueError(f"Declared padding/history mask must be -inf at score row {row_index}.")
        if not np.isfinite(values[row_index, ~mask]).all():
            raise ValueError(f"Eligible scores must be finite at score row {row_index}.")
        eligible_count = item_num - len(excluded)
        if eligible_count == 0:
            raise ValueError(f"No eligible candidates remain at score row {row_index}.")
        exclusions = [{"internal_item_id": 0, "item_id": item_tokens[0], "reason": "padding"}]
        exclusions.extend(
            {"internal_item_id": item, "item_id": item_tokens[item], "reason": "history"}
            for item in history_items
        )
        queries.append({
            "row_index": row_index, "query_id": query_id,
            "exported_rows": eligible_count, "exclusions": exclusions,
        })
        excluded_items.append(frozenset(excluded))
        history_count += len(history_items)
        exported_count += eligible_count

    result = {
        "schema_version": 1,
        "scope": "nonsequential_full_sort",
        "query_identity": "external user token; caller declares exact uid_series row alignment",
        "item_identity": "external item token in dataset internal-column order",
        "query_count": len(users),
        "item_count_including_padding": int(item_num),
        "exported_rows": exported_count,
        "excluded_rows": len(users) + history_count,
        "exclusions_by_reason": {"padding": len(users), "history": history_count},
        "queries": queries,
        "labels": "not_exported",
        "qrels_complete": False,
        "score_representation": "round-trip binary64 decimal",
        "privacy_note": "External user/item tokens are retained; export does not establish anonymity.",
    }
    out.mkdir()
    prediction_path = out / "predictions.csv"
    with prediction_path.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(("query_id", "item_id", "score"))
        for row_index, query_id in enumerate(query_tokens):
            for item, score in enumerate(values[row_index]):
                if item not in excluded_items[row_index]:
                    writer.writerow((query_id, item_tokens[item], repr(float(score))))
    checksum = hashlib.sha256()
    with prediction_path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            checksum.update(block)
    result["predictions_sha256"] = checksum.hexdigest()
    with (out / "exclusions.json").open("x", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")
    return result
