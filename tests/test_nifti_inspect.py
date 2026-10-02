"""Header-only NIfTI inspection without voxel reads, rendering, or network access."""

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
import qwen_mm_plugins_nifti as plugin
from pydantic import ValidationError
from qwen_mm_plugins_nifti.tools import inspect as inspect_tool

nib = pytest.importorskip("nibabel")


def _save_nifti(tmp_path, shape=(3, 4, 5), affine=None, units=("unknown", "unknown")):
    if affine is None:
        affine = np.diag([2.0, 3.0, 4.0, 1.0])
    image = nib.Nifti1Image(np.zeros(shape, dtype=np.int16), affine)
    image.header.set_xyzt_units(*units)
    path = tmp_path / "inspect.nii.gz"
    nib.save(image, path)
    return path


def _metadata(content):
    assert len(content) == 1, content
    assert content[0]["type"] == "text", content
    assert not content[0]["text"].startswith("Error"), content

    # Fail on NaN/Infinity, which are not valid JSON metadata values.
    def invalid_constant(value):
        raise AssertionError(f"Non-finite metadata value: {value}")

    return json.loads(content[0]["text"], parse_constant=invalid_constant)


def _forbid_voxel_reads(monkeypatch):
    def reject(*args, **kwargs):
        raise AssertionError("Inspection must not read voxel data, compute statistics, or render")

    monkeypatch.setattr(nib.arrayproxy.ArrayProxy, "__array__", reject)
    monkeypatch.setattr(nib.arrayproxy.ArrayProxy, "__getitem__", reject)
    monkeypatch.setattr(nib.dataobj_images.DataobjImage, "get_fdata", reject)
    monkeypatch.setattr(nib.dataobj_images.DataobjImage, "get_data", reject)
    monkeypatch.setattr(np, "percentile", reject)
    monkeypatch.setattr(np, "nanpercentile", reject)
    return reject


def test_nifti_inspect_reports_3d_header_without_voxel_reads(tmp_path, monkeypatch):
    path = _save_nifti(tmp_path)
    _forbid_voxel_reads(monkeypatch)

    metadata = _metadata(inspect_tool.handle({"file_path": str(path)}))

    assert metadata["shape"] == [3, 4, 5]
    assert metadata["ndim"] == 3
    assert metadata["dtype"] == "int16"
    assert metadata["voxel_spacing"] == [2.0, 3.0, 4.0]
    assert metadata["header_spatial_unit"] == "unknown"
    assert metadata["spatial_unit"] == "mm"
    assert metadata["spatial_unit_assumed"] is True
    np.testing.assert_allclose(metadata["affine"], np.diag([2.0, 3.0, 4.0, 1.0]))
    assert metadata["source_orientation"] == "RAS"
    assert metadata["closest_canonical_orientation"] == "RAS"
    assert metadata["max_obliquity_degrees"] == pytest.approx(0)
    assert metadata["volume_count"] == 1
    assert metadata["fourth_dimension"] is None
    assert not {"percentiles", "intensity_range", "modality", "window_preset", "timepoints"}.intersection(metadata)


@pytest.mark.parametrize("spatial_unit", ["mm", "meter", "micron"])
def test_nifti_inspect_preserves_known_spatial_units(tmp_path, spatial_unit):
    path = _save_nifti(tmp_path, units=(spatial_unit, "unknown"))

    metadata = _metadata(inspect_tool.handle({"file_path": str(path)}))

    assert metadata["header_spatial_unit"] == spatial_unit
    assert metadata["spatial_unit"] == spatial_unit
    assert metadata["spatial_unit_assumed"] is False
    assert metadata["voxel_spacing"] == [2.0, 3.0, 4.0]


@pytest.mark.parametrize("fourth_unit", ["unknown", "sec", "hz"])
def test_nifti_inspect_reports_4d_spacing_without_inventing_temporal_meaning(tmp_path, monkeypatch, fourth_unit):
    image = nib.Nifti1Image(np.zeros((3, 4, 5, 6), dtype=np.float32), np.eye(4))
    image.header.set_zooms((1.0, 1.0, 1.0, 2.5))
    image.header.set_xyzt_units("mm", fourth_unit)
    path = tmp_path / "four-dimensional.nii"
    nib.save(image, path)
    _forbid_voxel_reads(monkeypatch)

    metadata = _metadata(inspect_tool.handle({"file_path": str(path)}))

    assert metadata["shape"] == [3, 4, 5, 6]
    assert metadata["ndim"] == 4
    assert metadata["dtype"] == "float32"
    assert metadata["volume_count"] == 6
    assert metadata["fourth_dimension"] == {"spacing": 2.5, "unit": fourth_unit}
    assert not {"timepoints", "time_series", "repetition_time", "modality"}.intersection(metadata)


def test_nifti_inspect_reports_oblique_source_orientation_without_resampling(tmp_path, monkeypatch):
    theta = np.deg2rad(20.0)
    affine = np.array(
        [
            [-2.0 * np.cos(theta), -3.0 * np.sin(theta), 0.0, 10.0],
            [-2.0 * np.sin(theta), 3.0 * np.cos(theta), 0.0, 20.0],
            [0.0, 0.0, 4.0, 30.0],
            [0.0, 0.0, 0.0, 1.0],
        ]
    )
    path = _save_nifti(tmp_path, affine=affine)
    reject = _forbid_voxel_reads(monkeypatch)
    monkeypatch.setattr(nib, "as_closest_canonical", reject)
    original_bytes = path.read_bytes()

    metadata = _metadata(inspect_tool.handle({"file_path": str(path)}))

    assert metadata["source_orientation"] == "LAS"
    assert metadata["closest_canonical_orientation"] == "RAS"
    assert metadata["max_obliquity_degrees"] == pytest.approx(20.0, abs=1e-5)
    np.testing.assert_allclose(metadata["affine"], affine, atol=1e-6)
    assert path.read_bytes() == original_bytes


def test_nifti_inspect_handles_huge_shape_with_header_only_file(tmp_path, monkeypatch):
    # This header describes hundreds of terabytes but the fixture contains no voxel payload.
    # Inspection must succeed because it only reads the header, not validate/materialize pixels.
    shape = (32000, 32000, 32000, 6)
    header = nib.Nifti1Header()
    header.set_data_shape(shape)
    header.set_data_dtype(np.int16)
    header.set_sform(np.diag([2.0, 3.0, 4.0, 1.0]), code=1)
    header.set_zooms((2.0, 3.0, 4.0, 5.0))
    header["vox_offset"] = 352
    path = tmp_path / "huge-header-only.nii"
    with path.open("wb") as stream:
        header.write_to(stream)
    _forbid_voxel_reads(monkeypatch)

    metadata = _metadata(inspect_tool.handle({"file_path": str(path)}))

    assert path.stat().st_size == 352
    assert metadata["shape"] == list(shape)
    assert metadata["volume_count"] == 6
    assert metadata["fourth_dimension"] == {"spacing": 5.0, "unit": "unknown"}


def test_nifti_inspect_does_not_access_dataobj_property(tmp_path, monkeypatch):
    path = _save_nifti(tmp_path)
    loaded = nib.load(path)
    reject = _forbid_voxel_reads(monkeypatch)
    monkeypatch.setattr(nib, "load", lambda *args, **kwargs: loaded)
    monkeypatch.setattr(type(loaded), "dataobj", property(reject))

    metadata = _metadata(inspect_tool.handle({"file_path": str(path)}))

    assert metadata["shape"] == [3, 4, 5]


@pytest.mark.parametrize("shape", [(3, 4), (3, 4, 5, 2, 2)])
def test_nifti_inspect_rejects_unsupported_dimensions(tmp_path, shape):
    path = _save_nifti(tmp_path, shape=shape)

    content = inspect_tool.handle({"file_path": str(path)})

    assert len(content) == 1
    assert content[0]["type"] == "text"
    assert content[0]["text"].startswith("Error")
    assert "3D or 4D" in content[0]["text"]


@pytest.mark.parametrize("shape", [(0, 4, 5), (3, 4, 5, 0)])
def test_nifti_inspect_rejects_empty_spatial_or_volume_dimensions(tmp_path, shape):
    path = _save_nifti(tmp_path, shape=shape)

    content = inspect_tool.handle({"file_path": str(path)})

    assert len(content) == 1
    assert content[0]["type"] == "text"
    assert content[0]["text"].startswith("Error")
    assert "empty dimension" in content[0]["text"]


@pytest.mark.parametrize(
    "affine",
    [
        np.diag([0.0, 3.0, 4.0, 1.0]),
        np.diag([np.nan, 3.0, 4.0, 1.0]),
        np.diag([2.0, np.inf, 4.0, 1.0]),
    ],
    ids=["singular", "nan", "infinite"],
)
def test_nifti_inspect_returns_error_for_invalid_affine(tmp_path, monkeypatch, affine):
    path = _save_nifti(tmp_path)
    loaded = nib.load(path)
    loaded._affine = affine
    monkeypatch.setattr(nib, "load", lambda *args, **kwargs: loaded)
    _forbid_voxel_reads(monkeypatch)

    content = inspect_tool.handle({"file_path": str(path)})

    assert len(content) == 1
    assert content[0]["type"] == "text"
    assert content[0]["text"].startswith("Error")
    assert "affine" in content[0]["text"].lower()


@pytest.mark.parametrize(
    "arguments",
    [
        {},
        {"file_path": ""},
        {"file_path": None},
        {"file_path": True},
        {"file_path": 123},
        {"file_path": "/scan.nii", "budget": "small"},
    ],
)
def test_nifti_inspect_validates_its_header_only_input_model(arguments):
    spec = next(spec for spec in plugin.SPECS if spec.name == "nifti_inspect")
    with pytest.raises(ValidationError):
        spec.args_model.model_validate(arguments)

    content = inspect_tool.handle(arguments)

    assert len(content) == 1
    assert content[0]["type"] == "text"
    assert content[0]["text"].startswith("Error")


@pytest.mark.parametrize("case", ["missing", "relative", "url", "unsupported", "corrupt"])
def test_nifti_inspect_returns_text_errors_for_invalid_local_input(tmp_path, case):
    paths = {
        "missing": str(tmp_path / "missing.nii.gz"),
        "relative": "relative.nii",
        "url": "https://example.invalid/scan.nii.gz",
        "unsupported": str(tmp_path / "scan.txt"),
        "corrupt": str(tmp_path / "scan.nii.gz"),
    }
    if case in {"unsupported", "corrupt"}:
        Path(paths[case]).write_bytes(b"not a nifti file")

    content = inspect_tool.handle({"file_path": paths[case]})

    assert len(content) == 1
    assert content[0]["type"] == "text"
    assert content[0]["text"].startswith("Error")
    if case == "corrupt":
        assert "unsupported file type" not in content[0]["text"].lower()


def test_nifti_inspect_reports_its_own_optional_dependency_profile(tmp_path, monkeypatch):
    path = _save_nifti(tmp_path)
    monkeypatch.setitem(sys.modules, "nibabel", None)

    content = inspect_tool.handle({"file_path": str(path)})

    assert len(content) == 1
    assert content[0]["type"] == "text"
    assert content[0]["text"].startswith("Error")
    assert "Missing dependency" in content[0]["text"]
    assert "qwen-mm-plugins[nifti]" in content[0]["text"]


def test_nifti_inspect_needs_neither_rendering_dependencies_nor_sibling_capabilities(tmp_path):
    path = _save_nifti(tmp_path)
    repo = Path(__file__).resolve().parents[1]
    script = """
import importlib.abc
import json
import sys

sys.path[:0] = [sys.argv[1], sys.argv[2]]

class BlockRenderingImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        root = fullname.split('.')[0]
        if root.startswith('qwen_mm_plugins_') and root != 'qwen_mm_plugins_nifti':
            raise ImportError('Inspection must not import sibling ' + fullname)
        if root in {'PIL', 'matplotlib'} or fullname.startswith('qwen_mm_plugins_nifti.renderers'):
            raise ImportError('Inspection must not import rendering dependency ' + fullname)

sys.meta_path.insert(0, BlockRenderingImports())
import qwen_mm_plugins_nifti as plugin
assert not {'numpy', 'nibabel', 'PIL'}.intersection(sys.modules)
content = plugin.get_handler('nifti_inspect')({'file_path': sys.argv[3]})
assert len(content) == 1 and content[0]['type'] == 'text', content
metadata = json.loads(content[0]['text'])
assert metadata['shape'] == [3, 4, 5], metadata
assert not {'PIL', 'matplotlib'}.intersection(sys.modules)
"""
    result = subprocess.run(
        [sys.executable, "-I", "-c", script, str(repo / "src"), str(repo / "src/capabilities/nifti"), str(path)],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
