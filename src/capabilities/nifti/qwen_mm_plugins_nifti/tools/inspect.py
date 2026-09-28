"""MCP entry point for header-only local NIfTI inspection."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from shared.content import require_file, text_error


class NiftiInspectArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    file_path: str = Field(min_length=1, strict=True)


TOOL = {"name": "nifti_inspect", "args": NiftiInspectArgs}


def handle(arguments: dict[str, Any]) -> list[dict[str, Any]]:
    """Inspect a local 3D or 4D NIfTI header without reading voxel values or producing images.

    Return one JSON text block containing shape, ndim, stored dtype, voxel_spacing, affine,
    source_orientation, closest_canonical_orientation, max_obliquity_degrees, and volume_count.
    Axis codes describe the closest directions; oblique voxel axes need not be anatomical axes.
    No resampling, intensity statistics, modality inference, or image rendering is performed.

    The spatial_unit is taken from header_spatial_unit, except unknown units default to mm and
    set spatial_unit_assumed to true. Values and affine are not converted between units.
    For 4D inputs, fourth_dimension reports the fourth-axis spacing and header unit; its semantic
    meaning is not inferred as time. For 3D inputs it is null and volume_count is 1.
    To see slices, call nifti_render_slices independently. The input file is never modified.

    Args:
        file_path: Absolute path to a local .nii or .nii.gz file. URLs are not supported.
    """
    try:
        path = NiftiInspectArgs.model_validate(arguments).file_path
    except ValidationError as exc:
        return text_error(f"Invalid NIfTI options: {exc}")

    if "://" in path or not Path(path).is_absolute():
        return text_error("file_path must be an absolute local .nii or .nii.gz path; URLs are not supported")
    if not path.lower().endswith((".nii", ".nii.gz")):
        return text_error("unsupported file type; nifti_inspect accepts local .nii and .nii.gz files")
    if error := require_file(path):
        return error

    from qwen_mm_plugins_nifti.metadata import header_metadata, load_image

    try:
        _, metadata = header_metadata(load_image(path))
        return [{"type": "text", "text": json.dumps(metadata, ensure_ascii=False, indent=2, allow_nan=False)}]
    except ImportError:
        return text_error('Missing dependency. Install with: pip install "qwen-mm-plugins[nifti]"')
    except Exception as exc:
        return text_error(f"Error inspecting NIfTI file: {exc}")
