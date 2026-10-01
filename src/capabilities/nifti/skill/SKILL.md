---
name: qwen-mm-plugins-nifti
description: Inspect local NIfTI (.nii/.nii.gz) header metadata or render slices with shared intensity normalization and window presets. Use for checking volume geometry, NIfTI viewing, choosing slices or windows, and verifying effective display settings.
---

# NIfTI Volume Inspection

Use the `qwen-mm-plugins-nifti` MCP server's two tools according to the request:

- `nifti_inspect`: read header metadata when the user asks about shape, dtype,
  spacing, units, affine, orientation, obliquity, or the number of 3D volumes.
  It returns JSON in a text block without scanning voxel intensities or rendering
  images. It cannot determine intensity ranges, modality, or anatomy from pixels.
- `nifti_render_slices`: render images with configurable slice selection and
  intensity/window mapping. Call it directly for viewing; inspection is optional,
  not a prerequisite or a stateful initialization step.

When available, prefer these tools for their respective NIfTI tasks. Respect an
explicit request to use another tool.

## Read and verify

Pass an absolute `.nii` or `.nii.gz` file path to either tool. Both read the source
without modifying it. Rendering in the default native mode returns text and image blocks;
if `QWEN_MM_NATIVE_MODE=0`, the framework's caption fallback can send rendered
slices to the configured VL endpoint.

With only `file_path`, `nifti_render_slices` selects three uniformly spaced interior slices
along **source voxel axis 2**. Positions come from a five-point grid with its
endpoints discarded, rounded to source indices. Small dimensions can resolve
to fewer unique slices. Axis 2 is not necessarily anatomical axial/Z: check
the reported affine, closest orientation codes, and obliquity. In-plane axes
are reordered/flipped for display; no anatomical resampling is performed.

For 4D inputs, rendering defaults to the first 3D volume. `volumes` selects 1-based
volume pages, for example `"1,3"`; `max_volumes` caps this selection. The fourth
dimension is not automatically interpreted as time. Spatial units follow the
header; an unknown unit is explicitly reported as assumed mm.

## Select slices and intensity

- Set `slice_axis` to 0, 1, or 2 and `num_slices` for evenly spaced slices.
- For exact locations, set either `slice_indices` (0-based) or `slice_positions`
  (0–1 along the source axis). Either overrides `num_slices`; they cannot be
  combined. Duplicate resolved indices are returned once, in requested order.
- `intensity_mode="auto_volume"` uses one shared P1–P99 range per selected 3D
  volume. `percentile_low` and `percentile_high` adjust the bounds. Large
  volumes use a deterministic grid approximation; the response identifies
  exact/sampled statistics and the effective range. Sampling statistics does
  not subsample the displayed planes.
- `intensity_mode="window"` requires both `window_center` and `window_width`.
- `intensity_mode="preset"` requires `window_preset`: `ct_brain`,
  `ct_soft_tissue`, `ct_lung`, or `ct_bone`. Presets assume HU-like CT values;
  NIfTI alone does not establish modality or calibrated intensity units.
  Use a preset when requested or supported by user-provided acquisition
  context, and distinguish a suggested window from the one actually applied.

For metadata-only requests, report the relevant header values, preserving any
unit assumption and the distinction between voxel axes and anatomical axes.
Inspection does not choose slices or apply normalization; do not invent display
settings for that response. The fourth dimension is not necessarily time.

For rendered views, report the tool used, selected volume(s), source axis and resolved indices,
intensity mode and effective bounds, and whether statistics were sampled.
Mention any response-size truncation or assumed unit relevant to the request.
Use the returned configuration rather than reconstructing it from requested
arguments. If more slices are needed, request the omitted indices/volumes in
another call. This tool provides visualization, not a clinical diagnosis.
