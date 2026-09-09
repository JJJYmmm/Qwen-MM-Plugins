"""MCP tool modules. Each module exports TOOL and handle; discovered at startup by build_registry.

MemoryRef lives here rather than in a helper module because every tool but watch_and_answer starts
from it: the two fields are how a memory is addressed, and they mirror service.memory_dir's rules.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class MemoryRef(BaseModel):
    """Every tool locates a memory by video path, optionally with a namespace."""

    video_path: str | None = Field(
        default=None, description="Absolute path to the source video; memory is read from <video_path>.memory/."
    )
    namespace: str | None = Field(
        default=None,
        description="Memory name. Pass video_path too when MEM_LOCAL_DIR is unset; otherwise the "
        "memory is read from the configured shared root.",
    )
