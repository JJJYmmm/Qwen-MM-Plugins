---
name: qwen-mm-plugins-cua
description: Observe and operate native desktop applications through a small grounded interface. Use for real GUI tasks that need screenshots, accessibility state, clicks, typing, keys, scrolling, dragging, or waiting for visible state changes.
---

# Desktop control

Use the narrow CUA tools as one observation–action loop:

1. Use `list_apps` only when the application name or bundle id is uncertain.
2. Call `get_app_state` before acting.
3. Call exactly one action tool: `click`, `type_text`, `press_key`, `scroll`, `drag`, or `set_value`.
   Use an `element_token` when available or coordinates bound to that state's `snapshot_id`.
4. Judge the result only from the fresh state returned by the action. Repeat from that new state if
   more work remains.
5. Use `wait` for delayed transitions instead of repeatedly clicking.

Prefer semantic element targets over coordinates. Use screenshot coordinates for custom-drawn
content that is missing or misleading in the accessibility tree. A snapshot becomes stale after
any action or wait; never reuse its element tokens or coordinates.

Each screenshot is immediately preceded by its authoritative `H×W` pixel frame. Harnesses may
resize the displayed image, so always ground absolute `x,y` in that stated original PNG frame, not
in the apparent rendered size.

Do not enable automatic click retries unless repeating that specific click is safe. With
`retry_if_unverified=true`, the bounded retry ladder ends in one real OS-pointer click by default
if all ordinary routes leave state unchanged. That final route foregrounds the exact window and
moves the physical cursor. Set `allow_global_pointer_fallback=false` when cursor movement or focus
stealing is undesirable. Do not perform irreversible or externally consequential actions without
the user's authorization.

Use `click(count=2)` for a double click and `press_key` with `modifiers` for a hotkey. Use
`set_value` for deterministic native AX values, but prefer `type_text` for free-form web input.
Before a modified key targets a text field, establish real field focus with `click`; a hotkey does
not itself guarantee that focus.

The server intentionally exposes nine narrow tools rather than Cua Driver's full roster. The
driver's optional Skill pack is an implementation detail and should not be installed or invoked
alongside this Skill.
