from __future__ import annotations

import base64
import os
from pathlib import Path
from typing import Any

from pydantic import Field

from shared.content import json_text

from .. import watch
from ..service import DEFAULT_OMNI_MODEL, load_store, memory_label
from . import MemoryRef

# Replay sends clips inline as base64 (~3.5 MB per 30s clip), so an unbounded selection turns into a
# request the endpoint will reject. Same bound the core uses when it suggests replay candidates. Read
# by the schema and the description below, so it has to be bound before them.
REPLAY_CAP = max(1, watch.REPLAY_N)


class ReplayAndAnswerArgs(MemoryRef):
    question: str = Field(description="What to determine from watching the clips.")
    idxs: list[int] = Field(
        description="Clip indices to re-watch, e.g. suggested_replay_idxs from plan_and_search "
        f"or idxs from search_dialogue / get_timeline. At most {REPLAY_CAP} are watched per call — "
        "pick the most promising ones; extras come back in dropped_idxs."
    )
    evidence: str = Field(default="", description="Optional text context to give the model alongside the clips.")
    model: str | None = Field(
        default=None,
        description="Omni model for this call. Leave unset to use the configured default "
        f"({DEFAULT_OMNI_MODEL}). It need not match the model the memory was built with.",
    )


TOOL: dict[str, Any] = {
    "name": "replay_and_answer",
    "description": "Re-watch specific source clips WITH THEIR AUDIO and have the omni model answer from "
    "what it actually sees and hears. Reach for this only when the stored memory cannot settle the "
    "question — reading detail back off the original video is the one thing the read-only tools "
    f"cannot do. Watches at most {REPLAY_CAP} clips per call. Requires an omni model endpoint.",
    "args": ReplayAndAnswerArgs,
}


def replay_and_answer(
    video_path: str | None = None,
    namespace: str | None = None,
    question: str = "",
    idxs: list[int] | None = None,
    evidence: str = "",
    model: str | None = None,
) -> dict[str, Any]:
    """Re-watch the given clips WITH THEIR AUDIO and let the omni model answer from what it sees.

    Use this only when the stored text memory cannot settle the question — reading a frame off the
    original video is the one thing the read-only tools cannot do. `evidence` is optional context to
    give the model alongside the clips (e.g. what plan_and_search returned).

    `model` picks the omni model for this one call, defaulting to whatever the endpoint is configured
    with. It need not be the model the memory was built with — a build takes tens of minutes and may
    have used a cheaper one, while a single replay can afford the better one.

    Clips go inline as base64, ~3.5 MB per 30s clip, so the request grows fast. Beyond REPLAY_CAP the
    extra clips are dropped and reported in `dropped_idxs` rather than silently truncated.
    """
    from . import mem_core as _mc  # local import: only the replay path needs the omni client

    store = load_store(video_path, namespace)
    by_idx = {c.get("idx"): c for c in (store.clips or [])}
    wanted, dropped = list(idxs or []), []
    if len(wanted) > REPLAY_CAP:
        wanted, dropped = wanted[:REPLAY_CAP], wanted[REPLAY_CAP:]
    uris, used, missing, nbytes = [], [], [], 0
    for i in wanted:
        c = by_idx.get(int(i))
        path = (c or {}).get("oss_key") or (c or {}).get("path")
        if not path or not os.path.exists(path):
            missing.append(int(i))
            continue
        raw = Path(path).read_bytes()
        nbytes += len(raw)
        uris.append("data:video/mp4;base64," + base64.b64encode(raw).decode())
        used.append(int(i))
    if not uris:
        return {
            "label": memory_label(video_path, namespace),
            "error": "none of the requested clips are available on disk",
            "missing_idxs": missing,
            "hint": "get_moment reports clip_path per clip; a memory built elsewhere may have lost them",
        }
    used_model = model or _mc.MODEL
    out = ""
    for out in _mc.replay_answer_stream(_mc.get_client(), uris, evidence, question, model_override=model):
        pass
    res = {
        "label": memory_label(video_path, namespace),
        "question": question,
        "answer": out,
        "watched_idxs": used,
        "model": used_model,
        "sent_mb": round(nbytes * 4 / 3 / 1048576, 1),
    }
    if missing:
        res["missing_idxs"] = missing
    if dropped:
        res["dropped_idxs"] = dropped
        res["note"] = f"only the first {REPLAY_CAP} clips were sent; call again for the rest if needed"
    return res


def handle(arguments: dict[str, Any]) -> list[dict[str, str]]:
    return [json_text(replay_and_answer(**arguments))]
