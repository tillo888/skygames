from __future__ import annotations

from typing import List, Optional


def rank_entries(entries: List[dict], order: str) -> List[dict]:
    """entries: [{flyer, score (None = DNF), ...}]. Competition ranking
    (1, 2, 2, 4); DNF entries go last with rank None."""
    valid = [e for e in entries if e.get("score") is not None]
    dnf = [e for e in entries if e.get("score") is None]
    valid.sort(key=lambda e: e["score"], reverse=(order == "desc"))
    out, prev, prev_rank = [], None, 0
    for i, e in enumerate(valid, start=1):
        r = prev_rank if (prev is not None and abs(e["score"] - prev) < 1e-9) else i
        out.append({**e, "rank": r})
        prev, prev_rank = e["score"], r
    best: Optional[float] = valid[0]["score"] if valid else None
    for e in out:
        e["behind_leader"] = None if best is None else abs(e["score"] - best)
    out += [{**e, "rank": None, "behind_leader": None} for e in dnf]
    return out
