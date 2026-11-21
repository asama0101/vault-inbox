from __future__ import annotations

from .meta import MetaStore


def _active_ids(store: MetaStore) -> set[str]:
    return {d.id for d in store.docs() if d.state == "active"}


def dangling(store: MetaStore) -> list[dict]:
    """Relations whose src or dst is not an active doc, except kept ones."""
    active = _active_ids(store)
    return [
        {"src": r["src"], "dst": r["dst"], "kind": r["kind"]}
        for r in store.relations()
        if not r.get("kept") and (r["src"] not in active or r["dst"] not in active)
    ]


def expand(store: MetaStore, hit_ids: list[str]) -> dict:
    """Hits plus direct neighbours (one hop, both ways), minus superseded versions."""
    active = _active_ids(store)
    rels = [r for r in store.relations() if r["src"] in active and r["dst"] in active]
    materials = list(dict.fromkeys(hit_ids))
    for hit in hit_ids:
        for r in rels:
            if hit in (r["src"], r["dst"]):
                for other in (r["src"], r["dst"]):
                    if other not in materials:
                        materials.append(other)
    superseded = {r["dst"] for r in rels if r["kind"] == "supersedes"}
    materials = [m for m in materials if m not in superseded]
    conflicts = [
        [r["src"], r["dst"]]
        for r in rels
        if r["kind"] == "conflicts_with"
        and r["src"] in materials
        and r["dst"] in materials
    ]
    return {"materials": materials, "conflicts": conflicts}
