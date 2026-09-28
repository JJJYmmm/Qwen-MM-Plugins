"""Shared header-only NIfTI loading and spatial metadata, without reading voxel values."""

from __future__ import annotations

from typing import Any


def load_image(path: str):
    """Open a 3D/4D NIfTI lazily, validating dimensions without materializing its data."""
    import nibabel as nib

    image = nib.load(path)
    if image.ndim not in (3, 4):
        raise ValueError(f"NIfTI supports 3D or 4D images, got {image.ndim}D shape {image.shape}")
    if any(size < 1 for size in image.shape):
        raise ValueError(f"NIfTI image has an empty dimension: {image.shape}")
    return image


def header_metadata(image) -> tuple[object, dict[str, Any]]:
    """Return orientation and JSON-ready header metadata without accessing ``dataobj``."""
    import nibabel as nib
    import numpy as np

    affine = np.asarray(image.affine)
    if affine.shape != (4, 4) or not np.isfinite(affine).all():
        raise ValueError("NIfTI affine must be a finite 4x4 matrix")
    source_codes = nib.orientations.aff2axcodes(affine)
    source_orientation = "".join(code or "?" for code in source_codes)
    orientation = nib.orientations.io_orientation(affine)
    if np.isnan(orientation[:, 0]).any():
        raise ValueError("Cannot determine all three spatial axes from the NIfTI affine")
    display_affine = affine.dot(nib.orientations.inv_ornt_aff(orientation, image.shape))
    display_codes = nib.orientations.aff2axcodes(display_affine)
    display_orientation = "".join(code or "?" for code in display_codes)
    obliquity_degrees = float(np.max(np.rad2deg(nib.affines.obliquity(affine))))

    shape = [int(size) for size in image.shape]
    spacing = [float(value) for value in image.header.get_zooms()]
    header_space_unit, fourth_unit = image.header.get_xyzt_units()
    space_unit_assumed = header_space_unit == "unknown"
    return orientation, {
        "shape": shape,
        "ndim": image.ndim,
        "dtype": str(image.get_data_dtype()),
        "voxel_spacing": spacing[:3],
        "header_spatial_unit": header_space_unit,
        "spatial_unit": "mm" if space_unit_assumed else header_space_unit,
        "spatial_unit_assumed": space_unit_assumed,
        "affine": affine.tolist(),
        "source_orientation": source_orientation,
        "closest_canonical_orientation": display_orientation,
        "max_obliquity_degrees": obliquity_degrees,
        "volume_count": shape[3] if image.ndim == 4 else 1,
        "fourth_dimension": {"spacing": spacing[3], "unit": fourth_unit} if image.ndim == 4 else None,
    }
