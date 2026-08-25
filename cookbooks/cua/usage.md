# CUA cookbook

`qwen-mm-plugins-cua` controls native desktop applications through nine model-visible tools. It
uses the separately installed [Cua Driver](https://github.com/trycua/cua) for capture, accessibility,
Retina/downscale mapping, and input delivery.

## Setup

Install Cua Driver 0.20.0 or newer with its official installer:

```bash
/bin/bash -c "$(curl -fsSL https://cua.ai/driver/install.sh)"
cua-driver --version
cua-driver permissions status       # macOS
qwen-mm-plugins-cua --check-system
```

The adapter resolves `QWEN_MM_CUA_DRIVER_PATH` first, then `PATH`,
`~/.local/bin/cua-driver`, and the standard macOS app-bundle path. It never installs Cua Driver's
optional Skill pack and does not register the driver's complete MCP server.

## Tool boundary

- `list_apps`: find installed or running applications without exposing driver internals.
- `get_app_state`: select an ordinary app window and return its AX state plus optional PNG.
- `click`: semantic or screenshot-bound pointer action; `count=2` is a double click.
- `type_text`: insert text into an exact element, screenshot point, or focused control.
- `press_key`: send one key, optional modifiers (routed through the dedicated hotkey action), and
  optional repetition. Focus a text field first; the hotkey does not establish field focus.
- `scroll`: scroll a focused region, semantic element, or screenshot point.
- `drag`: perform a screenshot-bound drag gesture.
- `set_value`: set a native accessibility value on an exact element.
- `wait`: poll a bounded state condition and return one final current snapshot.

Every action tool returns fresh post-action state. Action schemas are intentionally separate so the
model does not need to select an action enum inside one large object or reason about fields belonging
to unrelated actions.

Pixel coordinates use the PNG returned by `get_app_state`; `relative_1000` maps `(0, 0)` to the
top-left and `(1000, 1000)` to the bottom-right. Both forms require that snapshot's `snapshot_id`.
The driver performs the actual Retina and capture-downscale conversion. Immediately before every
image block, the adapter emits its authoritative `H×W` and absolute `x,y` ranges. Use that original
PNG frame even when a harness visually resizes the image.

`delivery=auto` starts in the background. It escalates only for `click` when
`retry_if_unverified=true`, which asserts that repeating the click is safe. The bounded ladder is
background semantic click, background pixel click at the same element, then foreground pixel
click, with a fresh observation between attempts. If all three leave state unchanged, the default
final fallback foregrounds and revalidates the exact window, maps the snapshot point through the
current window and desktop PNG dimensions, verifies cursor readback, and delivers one desktop
`global_input` click. Set `allow_global_pointer_fallback=false` on a safe retry to stop before that
last step.

PID/window pixel delivery is not necessarily equivalent to a physical mouse click: Cua Driver may
still route it through accessibility hit-testing. The desktop fallback is accepted only when the
driver reports `route=global_input`; unprovable window bounds, an off-Space target, cursor mismatch,
or a prior state change causes it to fail closed.

## Verification matrix

| App/surface | Target | Expected evidence |
|---|---|---|
| Music | Standard playback control | Element-token click changes fresh state or playback UI |
| Music | Custom sidebar/search row | Semantic or screenshot click changes selected content |
| Music | Search-result card/cell | Fresh state navigates to the result; no driver-success-only claim |
| Music | Track row | Pixel double-click starts playback |
| Chrome | Main browser window | Selector rejects narrow helper surfaces and returns a normal PNG |
| Chrome | Page coordinate | Click uses the exact returned PNG dimensions, including Retina/downscale |
| Either | Off-Space/unprovable capture | Pixel action fails closed; semantic token may remain usable |
| Either | Stale snapshot | Adapter rejects the action before input delivery |

## Current macOS findings

These are regression cases for the adapter, not app-specific instructions in the Skill:

- Music sidebar rows and standard controls respond to semantic element clicks. On Music's custom
  recent-search cards, PID/window element and pixel clicks can both return through the accessibility
  route without activating the card. A verified desktop `global_input` click at the same mapped
  point does activate it; this is the regression case covered by the final safe-retry fallback.
- Chrome's normal window and PDF-viewer controls respond to both semantic and correctly mapped pixel
  clicks. Chrome can also expose narrow helper surfaces, move between Spaces, and change screenshot
  dimensions while keeping the same window id. Always use a new main-window snapshot; the adapter
  refuses off-Space or otherwise unprovable frames instead of reusing their coordinates.
