"""Offline coverage for the narrow Cua Driver adapter."""

from __future__ import annotations

import json
import stat

import pytest
import qwen_mm_plugins_cua
from qwen_mm_plugins_cua import driver
from qwen_mm_plugins_cua.tools import click, get_app_state, list_apps, press_key, set_value, type_text, wait

MAIN_WINDOW = {
    "app_name": "Music",
    "bounds": {"x": 100.0, "y": 100.0, "width": 800.0, "height": 600.0},
    "is_on_screen": True,
    "layer": 0,
    "on_current_space": True,
    "pid": 123,
    "title": "Music",
    "window_id": 42,
    "z_index": 5,
}
NARROW_WINDOW = {
    "app_name": "Music",
    "bounds": {"x": 0.0, "y": 0.0, "width": 1280.0, "height": 35.0},
    "is_on_screen": True,
    "layer": 0,
    "on_current_space": True,
    "pid": 123,
    "title": "",
    "window_id": 7,
    "z_index": 0,
}


def _state(snapshot: int, label: str = "Search", screenshot: str = "same-image") -> dict:
    snapshot_id = f"s{snapshot:08x}"
    return {
        "element_count": 2,
        "elements": [
            {
                "depth": 0,
                "element_index": 0,
                "element_token": f"{snapshot_id}:0",
                "frame": {"x": 100.0, "y": 100.0, "w": 800.0, "h": 600.0},
                "label": "Music",
                "role": "AXWindow",
            },
            {
                "depth": 1,
                "element_index": 1,
                "element_token": f"{snapshot_id}:1",
                "frame": {"x": 110.0, "y": 120.0, "w": 40.0, "h": 20.0},
                "label": label,
                "role": "AXCell",
            },
        ],
        "pid": 123,
        "screenshot_frame_valid": True,
        "screenshot_height": 1200,
        "screenshot_mime_type": "image/png",
        "screenshot_png_b64": screenshot,
        "screenshot_scale": 2.0,
        "screenshot_width": 1600,
        "snapshot_id": snapshot_id,
        "tree_markdown": f"Music\n  AXCell {label}",
        "window_bounds": MAIN_WINDOW["bounds"],
        "window_id": 42,
    }


class FakeClient:
    def __init__(self, states: list[dict]) -> None:
        self.states = list(states)
        self.calls: list[tuple[str, dict]] = []
        self.cursor = (0.0, 0.0)

    def call(self, tool: str, arguments: dict | None = None, *, timeout=None) -> dict:
        args = arguments or {}
        self.calls.append((tool, dict(args)))
        if tool == "list_apps":
            return {
                "apps": [
                    {
                        "active": False,
                        "bundle_id": "com.apple.Music",
                        "name": "Music",
                        "pid": 123,
                        "running": True,
                    }
                ]
            }
        if tool == "list_windows":
            return {"windows": [NARROW_WINDOW, MAIN_WINDOW]}
        if tool == "get_window_state":
            assert self.states, "test did not provide enough fresh states"
            return self.states.pop(0)
        if tool == "bring_to_front":
            return {"activated": True, "exact_window_effect": {"verified": True}}
        if tool == "get_desktop_state":
            return {
                "screen_width": 1512,
                "screen_height": 982,
                "screenshot_width": 3024,
                "screenshot_height": 1964,
            }
        if tool == "move_cursor":
            self.cursor = (args["x"] / 2, args["y"] / 2)
            return {"route": "global_input"}
        if tool == "get_cursor_position":
            return {"x": self.cursor[0], "y": self.cursor[1]}
        if tool in {"click", "double_click", "type_text", "press_key", "hotkey", "scroll", "drag", "set_value"}:
            if tool == "click" and args.get("scope") == "desktop":
                return {"effect": "unverifiable", "route": "global_input", "tool": tool}
            return {"effect": "unverifiable", "tool": tool}
        if tool == "launch_app":
            return {"bundle_id": "com.apple.Music", "name": "Music", "pid": 123}
        raise AssertionError(f"unexpected driver tool: {tool}")


class TransientStateClient(FakeClient):
    def call(self, tool: str, arguments: dict | None = None, *, timeout=None) -> dict:
        if tool == "get_window_state" and self.states and self.states[0].get("status") == "refused":
            self.calls.append((tool, dict(arguments or {})))
            return self.states.pop(0)
        return super().call(tool, arguments, timeout=timeout)


@pytest.fixture(autouse=True)
def _clean_runtime(monkeypatch):
    driver.reset_runtime_for_tests()
    yield
    driver.reset_runtime_for_tests()


def _install_fake(monkeypatch, *states: dict) -> FakeClient:
    fake = FakeClient(list(states))
    monkeypatch.setattr(driver, "_CLIENT", fake)
    return fake


def _payload(blocks: list[dict]) -> dict:
    assert blocks[0]["type"] == "text"
    assert not blocks[0]["text"].startswith("Error:")
    return json.loads(blocks[0]["text"])


def test_registry_exposes_only_nine_narrow_tools():
    assert [spec.name for spec in qwen_mm_plugins_cua.SPECS] == [
        "click",
        "drag",
        "get_app_state",
        "list_apps",
        "press_key",
        "scroll",
        "set_value",
        "type_text",
        "wait",
    ]
    schemas = {spec.name: spec.input_schema for spec in qwen_mm_plugins_cua.SPECS}
    assert "action" not in schemas["click"]["properties"]
    assert "text" not in schemas["click"]["properties"]
    assert "direction" not in schemas["type_text"]["properties"]
    assert schemas["set_value"]["required"] == ["element_token", "value"]
    assert all(schema.get("additionalProperties") is False for schema in schemas.values())


def test_driver_requires_020_or_newer(tmp_path):
    binary = tmp_path / "cua-driver"
    binary.write_text("#!/bin/sh\necho 'cua-driver 0.19.3'\n")
    binary.chmod(binary.stat().st_mode | stat.S_IXUSR)

    with pytest.raises(driver.CuaError, match=r"0\.20\.0\+"):
        driver.DriverClient(str(binary)).ensure_compatible()


def test_main_window_selection_rejects_narrow_surface():
    selected, reason = driver.select_window([NARROW_WINDOW, MAIN_WINDOW])

    assert selected["window_id"] == 42
    assert reason["rejected_window_ids"] == [7]


def test_relative_coordinates_bind_to_png_dimensions(monkeypatch):
    _install_fake(monkeypatch, _state(1))
    state = _payload(get_app_state.handle({"app": "Music"}))
    assert state["pixel_actions"]["snapshot_binding"] == "s00000001"

    record = driver.SNAPSHOTS._by_id["s00000001"]
    assert driver.convert_point(record, 500, 250, "relative_1000") == pytest.approx((799.5, 299.75))


def test_image_is_immediately_preceded_by_its_absolute_coordinate_frame(monkeypatch):
    _install_fake(monkeypatch, _state(1))

    blocks = get_app_state.handle({"app": "Music"})

    assert blocks[-2]["type"] == "text"
    assert "H×W=1200×1600 px" in blocks[-2]["text"]
    assert "x∈[0,1600), y∈[0,1200)" in blocks[-2]["text"]
    assert blocks[-1]["type"] == "image"


def test_click_reobserves_and_verifies_state_change(monkeypatch):
    fake = _install_fake(monkeypatch, _state(1), _state(2, label="Song detail", screenshot="changed"))
    _payload(get_app_state.handle({"app": "Music"}))

    result = _payload(
        click.handle(
            {
                "app": "Music",
                "snapshot_id": "s00000001",
                "element_token": "s00000001:1",
                "expect": {"condition": "state_changed"},
            }
        )
    )

    assert result["state"]["snapshot_id"] == "s00000002"
    assert result["interaction"]["verification"]["verified"] is True
    click_calls = [args for tool, args in fake.calls if tool == "click"]
    assert click_calls == [
        {
            "pid": 123,
            "window_id": 42,
            "session": "qwen-mm-cua",
            "delivery_mode": "background",
            "element_token": "s00000001:1",
            "button": "left",
        }
    ]


def test_safe_auto_retry_converts_element_center_to_pixel(monkeypatch):
    fake = _install_fake(
        monkeypatch,
        _state(1),
        _state(2, label="Unrelated change", screenshot="cursor-moved"),
        _state(3, label="Opened", screenshot="changed"),
    )
    _payload(get_app_state.handle({"app": "Music"}))

    result = _payload(
        click.handle(
            {
                "app": "Music",
                "snapshot_id": "s00000001",
                "element_token": "s00000001:1",
                "retry_if_unverified": True,
                "expect": {"condition": "element_present", "query": "Opened"},
            }
        )
    )

    click_calls = [args for tool, args in fake.calls if tool == "click"]
    assert len(click_calls) == 2
    assert click_calls[0]["element_token"] == "s00000001:1"
    assert click_calls[1]["delivery_mode"] == "background"
    assert (click_calls[1]["x"], click_calls[1]["y"]) == pytest.approx((60, 60))
    assert result["interaction"]["verification"]["verified"] is True


def test_explicit_global_pointer_fallback_maps_and_verifies_desktop_click(monkeypatch):
    fake = _install_fake(
        monkeypatch,
        _state(1),
        _state(2),
        _state(3),
        _state(4),
        _state(5, label="Opened", screenshot="changed"),
    )
    _payload(get_app_state.handle({"app": "Music"}))

    result = _payload(
        click.handle(
            {
                "app": "Music",
                "snapshot_id": "s00000001",
                "element_token": "s00000001:1",
                "retry_if_unverified": True,
                "expect": {"condition": "element_present", "query": "Opened"},
            }
        )
    )

    click_calls = [args for tool, args in fake.calls if tool == "click"]
    assert len(click_calls) == 4
    assert [call.get("delivery_mode") for call in click_calls[:3]] == ["background", "background", "foreground"]
    assert click_calls[3] == {
        "scope": "desktop",
        "x": 260,
        "y": 260,
        "button": "left",
        "session": "qwen-mm-cua",
    }
    fallback = result["interaction"]["global_pointer_fallback"]
    assert fallback["attempted"] is True
    assert fallback["route_verified"] is True
    assert fallback["cursor_readback"] == {"x": 130.0, "y": 130.0}
    assert result["interaction"]["verification"]["verified"] is True


def test_global_pointer_fallback_refuses_an_off_space_window(monkeypatch):
    fake = _install_fake(monkeypatch, _state(1), _state(2), _state(3), _state(4))
    off_space = {**MAIN_WINDOW, "on_current_space": False}

    original_call = fake.call

    def call_with_off_space(tool: str, arguments: dict | None = None, *, timeout=None):
        if tool == "list_windows":
            fake.calls.append((tool, dict(arguments or {})))
            return {"windows": [NARROW_WINDOW, off_space]}
        return original_call(tool, arguments, timeout=timeout)

    monkeypatch.setattr(fake, "call", call_with_off_space)
    _payload(get_app_state.handle({"app": "Music"}))

    result = _payload(
        click.handle(
            {
                "app": "Music",
                "snapshot_id": "s00000001",
                "element_token": "s00000001:1",
                "retry_if_unverified": True,
                "allow_global_pointer_fallback": True,
                "expect": {"condition": "element_present", "query": "Opened"},
            }
        )
    )

    fallback = result["interaction"]["global_pointer_fallback"]
    assert fallback["attempted"] is False
    assert "current Space" in fallback["refused"]
    assert not [args for tool, args in fake.calls if tool == "click" and args.get("scope") == "desktop"]


def test_global_pointer_fallback_schema_requires_safe_retry_contract():
    ordinary = click.ClickArgs.model_validate(
        {
            "app": "Music",
            "snapshot_id": "s00000001",
            "x": 10,
            "y": 10,
        }
    )
    assert ordinary.allow_global_pointer_fallback is True

    with pytest.raises(ValueError, match="global pointer fallback requires"):
        click.ClickArgs.model_validate(
            {
                "app": "Music",
                "snapshot_id": "s00000001",
                "x": 10,
                "y": 10,
                "delivery": "foreground",
                "retry_if_unverified": True,
            }
        )


def test_stale_snapshot_fails_before_input(monkeypatch):
    fake = _install_fake(monkeypatch, _state(1), _state(2))
    _payload(get_app_state.handle({"app": "Music"}))
    _payload(get_app_state.handle({"app": "Music"}))

    blocks = click.handle(
        {
            "app": "Music",
            "snapshot_id": "s00000001",
            "element_token": "s00000001:1",
        }
    )

    assert "stale snapshot_id" in blocks[0]["text"]
    assert not [tool for tool, _ in fake.calls if tool == "click"]


def test_wait_returns_new_snapshot_when_condition_appears(monkeypatch):
    _install_fake(monkeypatch, _state(1), _state(2), _state(3, label="Ready"))
    _payload(get_app_state.handle({"app": "Music"}))

    result = _payload(
        wait.handle(
            {
                "condition": "element_present",
                "app": "Music",
                "query": "Ready",
                "timeout_seconds": 1,
                "poll_interval_seconds": 0.01,
                "include_screenshot": False,
            }
        )
    )

    assert result["wait_result"]["satisfied"] is True
    assert result["state"]["snapshot_id"] == "s00000003"


def test_observation_retries_without_repeating_input(monkeypatch):
    fake = TransientStateClient([_state(1), {"status": "refused"}, _state(2, label="Opened")])
    monkeypatch.setattr(driver, "_CLIENT", fake)
    _payload(get_app_state.handle({"app": "Music"}))

    result = _payload(
        click.handle(
            {
                "app": "Music",
                "snapshot_id": "s00000001",
                "element_token": "s00000001:1",
            }
        )
    )

    assert result["state"]["snapshot_id"] == "s00000002"
    assert len([tool for tool, _ in fake.calls if tool == "click"]) == 1
    assert len([tool for tool, _ in fake.calls if tool == "get_window_state"]) == 3


def test_list_apps_filters_without_resolving_a_window(monkeypatch):
    fake = _install_fake(monkeypatch)

    result = _payload(list_apps.handle({"query": "apple.music", "running_only": True}))

    assert result["count"] == 1
    assert result["apps"][0]["bundle_id"] == "com.apple.Music"
    assert [tool for tool, _ in fake.calls] == ["list_apps"]


def test_type_text_has_a_narrow_payload_and_returns_fresh_state(monkeypatch):
    fake = _install_fake(monkeypatch, _state(1), _state(2, label="Typed", screenshot="changed"))
    _payload(get_app_state.handle({"app": "Music"}))

    result = _payload(
        type_text.handle(
            {
                "app": "Music",
                "snapshot_id": "s00000001",
                "element_token": "s00000001:1",
                "text": "爱错",
            }
        )
    )

    calls = [args for tool, args in fake.calls if tool == "type_text"]
    assert calls == [
        {
            "pid": 123,
            "window_id": 42,
            "session": "qwen-mm-cua",
            "delivery_mode": "background",
            "element_token": "s00000001:1",
            "text": "爱错",
            "delay_ms": 30,
        }
    ]
    assert result["state"]["snapshot_id"] == "s00000002"


def test_press_key_combines_hotkey_modifiers_and_repeat(monkeypatch):
    fake = _install_fake(monkeypatch, _state(1), _state(2, label="Selected", screenshot="changed"))
    _payload(get_app_state.handle({"app": "Music"}))

    _payload(
        press_key.handle(
            {
                "app": "Music",
                "snapshot_id": "s00000001",
                "key": "down",
                "modifiers": ["shift"],
                "repeat": 2,
            }
        )
    )

    calls = [args for tool, args in fake.calls if tool == "press_key"]
    assert len(calls) == 2
    assert all(call["key"] == "down" and call["modifiers"] == ["shift"] for call in calls)


def test_set_value_uses_only_the_snapshot_bound_element(monkeypatch):
    fake = _install_fake(monkeypatch, _state(1), _state(2, label="Volume", screenshot="changed"))
    _payload(get_app_state.handle({"app": "Music"}))

    result = _payload(
        set_value.handle(
            {
                "app": "Music",
                "snapshot_id": "s00000001",
                "element_token": "s00000001:1",
                "value": "50",
            }
        )
    )

    calls = [args for tool, args in fake.calls if tool == "set_value"]
    assert calls == [
        {
            "pid": 123,
            "window_id": 42,
            "session": "qwen-mm-cua",
            "element_token": "s00000001:1",
            "value": "50",
        }
    ]
    assert result["state"]["snapshot_id"] == "s00000002"
