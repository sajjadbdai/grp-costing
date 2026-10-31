"""JSON file store with immutable revisions. Stdlib only.

Each saved estimate snapshots inputs, dimensions with original units,
rates, recipe, assumptions and result totals, so later rate changes never
rewrite history: they create a new revision instead.
"""

from __future__ import annotations

import json
import os
import time
import uuid


class StoreError(Exception):
    """Store unavailable or estimate not found."""


def _project_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def data_path():
    override = os.environ.get("GFPF_DATA_PATH")
    if override:
        return override
    return os.path.join(_project_root(), "data", "estimates.json")


def _load():
    path = data_path()
    if not os.path.exists(path):
        return {"estimates": []}
    try:
        with open(path, "r", encoding="utf-8-sig") as handle:
            data = json.load(handle)
    except (OSError, ValueError) as exc:
        raise StoreError("Saved estimates file is unreadable (%s)." % exc)
    if not isinstance(data, dict) or not isinstance(data.get("estimates"), list):
        raise StoreError("Saved estimates file has an unexpected format.")
    return data


def _save(data):
    path = data_path()
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)
    os.replace(tmp, path)


def save_new(record):
    """Store a first revision; returns {'id':..., 'rev': 1}."""
    data = _load()
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    estimate = {
        "id": uuid.uuid4().hex[:12],
        "label": str(record.get("label", "Untitled estimate")),
        "shape_id": record.get("shape_id"),
        "created_at": now,
        "updated_at": now,
        "revisions": [{"rev": 1, "saved_at": now, "snapshot": record}],
    }
    data["estimates"].insert(0, estimate)
    _save(data)
    return {"id": estimate["id"], "rev": 1}


def add_revision(estimate_id, snapshot):
    """Append an immutable revision; returns the new revision number."""
    data = _load()
    for estimate in data["estimates"]:
        if estimate["id"] == estimate_id:
            now = time.strftime("%Y-%m-%d %H:%M:%S")
            rev = max(r["rev"] for r in estimate["revisions"]) + 1
            estimate["revisions"].append({"rev": rev, "saved_at": now, "snapshot": snapshot})
            estimate["updated_at"] = now
            _save(data)
            return rev
    raise StoreError("Estimate %s not found." % estimate_id)


def get(estimate_id, rev=None):
    """Return (meta, revision); rev=None selects the latest revision."""
    for estimate in _load()["estimates"]:
        if estimate["id"] == estimate_id:
            revisions = estimate["revisions"]
            if rev is None:
                revision = revisions[-1]
            else:
                matches = [r for r in revisions if r["rev"] == int(rev)]
                if not matches:
                    raise StoreError("Revision %s not found." % rev)
                revision = matches[0]
            meta = {k: estimate[k] for k in ("id", "label", "shape_id", "created_at", "updated_at")}
            meta["rev_count"] = len(revisions)
            meta["rev_numbers"] = [r["rev"] for r in revisions]
            return meta, revision
    raise StoreError("Estimate %s not found." % estimate_id)


def list_all():
    """Newest-first summaries for the estimates page."""
    summaries = []
    for estimate in _load()["estimates"]:
        latest = estimate["revisions"][-1]["snapshot"]
        result = latest.get("result", {})
        summaries.append(
            {
                "id": estimate["id"],
                "label": estimate["label"],
                "shape_id": estimate["shape_id"],
                "revs": len(estimate["revisions"]),
                "qty": latest.get("qty"),
                "total_bd": result.get("total_bd"),
                "per_piece_bd": result.get("per_piece_bd"),
                "updated_at": estimate["updated_at"],
            }
        )
    return summaries