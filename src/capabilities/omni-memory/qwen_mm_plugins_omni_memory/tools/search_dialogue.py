from __future__ import annotations

from typing import Any

from pydantic import Field

from shared.content import json_text

from ..service import clip_utterances, embed_client, load_store, memory_label
from . import MemoryRef


class SearchDialogueArgs(MemoryRef):
    query: str = Field(
        description="What was said, phrased as a statement (e.g. 'someone offers to "
        "help with the dishes'), not as a question."
    )
    top_k: int = Field(default=8, ge=1, le=20)


TOOL: dict[str, Any] = {
    "name": "search_dialogue",
    "description": "Search spoken lines and get them back WITH the speaker attached (person_id + "
    "resolved name). Use it when the question is about who said what, or to find the "
    "moment a topic was discussed. Unlike a standalone ASR index, every line here is "
    "already bound to a person that persists across the whole video.",
    "args": SearchDialogueArgs,
}


def search_dialogue(
    video_path: str | None = None, namespace: str | None = None, query: str = "", top_k: int = 8
) -> dict[str, Any]:
    """Dialogue search that keeps speaker attribution — the thing a separate ASR index cannot do."""
    store = load_store(video_path, namespace)
    hits = store.search_episodic(query, client=embed_client(), k=max(1, min(int(top_k), 20)))
    eps = hits if isinstance(hits, list) else (hits.get("episodic") or [])
    lines = []
    for rec in eps:
        lines.extend(clip_utterances(store, rec))
    lines.sort(key=lambda x: (x["start_sec"], x["clip_idx"] or 0))
    return {"label": memory_label(video_path, namespace), "matched_clips": len(eps), "utterances": lines}


def handle(arguments: dict[str, Any]) -> list[dict[str, str]]:
    return [json_text(search_dialogue(**arguments))]
