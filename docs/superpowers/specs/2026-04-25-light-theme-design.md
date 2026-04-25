# Light Theme & Theme-Aware Cue Colors — Design

**Date:** 2026-04-25
**Status:** Draft

## Goal

Replace the no-op `Light` theme stub with a real light theme at parity with `Dark` for palette colors (no QSS port — palette only). Add a separate `System` theme that preserves the stub's pass-through behavior under an honest name. Refactor the theme infrastructure so future themes (Solarized Light, Solarized Dark) are ~20-line declarations. Make the cue color palette theme-aware via a new `color_name` cue property; preserve legacy `stylesheet["background"]` hexes without migration.

## Non-Goals

- Porting `dark/theme.qss` to a light variant. Light ships palette-only; the dark theme keeps its QSS.
- Light variants of dark theme assets (checkbox indicators, scrollbar arrows in `themes/dark/assets/`). The default Qt style draws these on light backgrounds.
- Live theme switching at runtime. `apply()` runs once at startup, as today; theme changes still require restart.
- Migrating legacy `stylesheet["background"]` hex values to `color_name`. Existing cues keep their custom hexes verbatim.
- Adding a "custom hex" picker UI. The cue picker remains the 7 named swatches plus "No color"; users with custom hexes set them via session-file edits or stylesheet text fields, as today.
- Bumping a session-format version flag. The new `color_name` property is additive; sessions saved by new LiSP and opened in old LiSP lose only the themed flag (the cue still has any legacy `stylesheet["background"]` if one was present).

## Architecture

### Theme infrastructure (`lisp/ui/themes/`)

A new `base.py` module introduces:

- **`CUE_COLOR_NAMES`** — module-level tuple of 7 canonical names: `("Red", "Orange", "Yellow", "Green", "Blue", "Purple", "Grey")`. Wire-format identifiers; never translated.
- **`DEFAULT_CUE_PALETTE`** — frozen `dict[str, str]` mapping each name to the existing 7 hexes (`#C03A2A`, `#D6761E`, `#C09A20`, `#3E8A3B`, `#3535B8`, `#7848A6`, `#6E6E6E`). Used by Dark, Light, and as the fallback in `cue_color_hex()` when no theme is active.
- **`ThemeColors`** — frozen dataclass with required base colors and optional explicit overrides for derived palette roles. The optional overrides exist because `lighter()`/`darker()` derivations don't always translate from dark to light (e.g., `foreground.darker(125)` on a light foreground produces a punchy `AlternateBase` band; an explicit subtle gray reads better).

  ```python
  @dataclass(frozen=True)
  class ThemeColors:
      background: QColor
      foreground: QColor
      text: QColor
      highlight: QColor
      bright_text: QColor | None = None        # default: QColor(255, 0, 0)
      highlighted_text: QColor | None = None   # default: QColor(0, 0, 0)
      alternate_base: QColor | None = None     # default: foreground.darker(125)
      light: QColor | None = None              # default: foreground.lighter(160)
      midlight: QColor | None = None           # default: foreground.lighter(125)
      dark: QColor | None = None               # default: foreground.darker(150)
      mid: QColor | None = None                # default: foreground.darker(125)
      cue_palette: Mapping[str, str] = field(default_factory=lambda: DEFAULT_CUE_PALETTE)
  ```

  `__post_init__` validates `set(cue_palette.keys()) == set(CUE_COLOR_NAMES)` and asserts each value matches `^#[0-9A-Fa-f]{6}$`. Misconfigured themes fail at definition time.

- **`BaseTheme`** — base class with class-level `Colors: ThemeColors` and `QssPath: str | None = None`. Provides `apply(qt_app)` which:
  1. Builds a `QPalette` using `Colors`, applying overrides where set and the existing dark-theme formulas elsewhere.
  2. Calls `qt_app.setPalette(palette)`.
  3. Sets module-level `_active = self` in `themes/__init__.py`.
  4. If `QssPath` is set, reads and applies the stylesheet.

The order matters: `_active` is set **before** the QSS read, so `cue_color_hex()` works correctly even if the QSS file is unreadable.

Two new helper functions in `themes/__init__.py`:

```python
def cue_color_hex(name: str) -> str:
    """Resolve a canonical name to the active theme's hex. '' → ''."""
    if not name:
        return ""
    if _active is not None and hasattr(_active, "Colors"):
        return _active.Colors.cue_palette[name]
    return DEFAULT_CUE_PALETTE[name]

def cue_palette() -> Mapping[str, str]:
    """Active theme's full {name: hex} mapping for picker UI."""
    if _active is not None and hasattr(_active, "Colors"):
        return _active.Colors.cue_palette
    return DEFAULT_CUE_PALETTE
```

### Concrete themes

**`themes/dark/dark.py`** (migrated):
```python
class Dark(BaseTheme):
    Colors = ThemeColors(
        background=QColor(30, 30, 30),
        foreground=QColor(52, 52, 52),
        text=QColor(230, 230, 230),
        highlight=QColor(65, 155, 230),
    )
    QssPath = os.path.join(os.path.dirname(__file__), "theme.qss")
```

**`themes/light/light.py`** (replacement):
```python
class Light(BaseTheme):
    Colors = ThemeColors(
        background=QColor(245, 245, 245),
        foreground=QColor(230, 230, 230),
        text=QColor(30, 30, 30),
        highlight=QColor(65, 155, 230),
        alternate_base=QColor(220, 220, 220),
        highlighted_text=QColor(255, 255, 255),
        bright_text=QColor(200, 0, 0),
    )
```

**`themes/system/system.py`** (new):
```python
from lisp.ui import themes

class System:
    """Pass-through. Applies no palette and no stylesheet — Qt's default style takes over."""

    def apply(self, qt_app):
        themes._active = self
```

`System` deliberately does not subclass `BaseTheme`; it has no `Colors` attribute. `cue_color_hex()` and `cue_palette()` check `hasattr(_active, "Colors")` and fall back to `DEFAULT_CUE_PALETTE` when the active theme has no `Colors`. System still sets `_active` so that consecutive `apply()` calls (e.g., in tests) end up with predictable state.

### Auto-discovery

No changes to `lisp/ui/themes/__init__.py:load_themes()`. The existing `load_classes` walker finds `Dark`, `Light`, `System` automatically. Settings dropdown via `themes_names()` — currently unsorted; out of scope for this change.

### Cue color model

**Cue property (`lisp/cues/cue.py`):**

Add `color_name = Property(default="")` alongside the existing properties. Permitted values: any element of `CUE_COLOR_NAMES`, or `""`. No runtime enforcement of the enum; consumers tolerate unknown names by treating them as `""` (defensive, but unlikely in practice given the picker writes only known values).

**Render-time resolution (one helper):**

Lives in `lisp/ui/themes/__init__.py` alongside `cue_color_hex` — it operates on a cue and returns a hex, all theme-related concerns:

```python
def cue_background_hex(cue) -> str:
    """Return the hex to paint for this cue, '' for none.
    Themed name takes precedence over legacy stylesheet hex."""
    if cue.color_name:
        return cue_color_hex(cue.color_name)
    return css_to_dict(cue.stylesheet).get("background", "")
```

Placed in `themes/__init__.py` rather than `lisp/cues/cue.py` because it depends on the active theme; `lisp/cues/` would be importing from `lisp/ui/`, which is a layering inversion.

**Render sites updated:**

- `lisp/plugins/list_layout/list_view.py:397-401` — `__updateItemStyle` swaps `css.get("background")` for `cue_background_hex(item.cue)`.
- `lisp/plugins/list_layout/playing_widgets.py:285` — same swap.
- `lisp/plugins/cart_layout/cue_widget.py:361-370` — `_updateStyle` passes the cue's `stylesheet` string directly to `setStyleSheet()`. For themed cues we inject the resolved hex into the CSS at apply time: parse with `css_to_dict`, set `"background"` to `themes.cue_color_hex(cue.color_name)` if `color_name` is set, re-serialize with `dict_to_css`, then pass to `setStyleSheet`. Also subscribe `_refreshStyle` to `cue.changed("color_name")` so theme-resolved cart cues repaint when the property changes.
- `lisp/ui/inspector/commit.py` — picker integration; see below.
- `lisp/ui/settings/cue_pages/cue_general.py:377, 414` — picker integration.

**Picker (`lisp/ui/widgets/cue_color_palette.py`):**

- `_Swatch` carries the canonical name (`"Red"`) instead of a hex string. At paint time, looks up the hex via `themes.cue_color_hex(name)`.
- `CueColorPalette.colorPicked` signal still carries `str` but the contract changes from "hex" to "canonical name or empty string".
- `setColor(name)` / `color()` deal in names. Calling `setColor("")` deselects all swatches.
- New: `setCustomHex(hex)` for when the cue has a legacy custom hex but no `color_name`. Clears the swatch selection and shows a small "custom: #aabbcc" annotation under the strip.
- `_SELECTION_RING_COLOR` and `_UNSELECTED_RING_COLOR` are derived at paint time from `QApplication.palette().color(QPalette.WindowText)` and `QPalette.Mid` (instead of hardcoded `#E6E6E6`/`#3C3C3C`).
- `_NONE_SLASH_COLOR = "#888888"` stays — neutral gray reads on both themes.
- `snap_to_palette()` and the `_HEX_RE`/`_parse_rgb` helpers are deleted. They have no remaining callers.

**Picker → cue write path:**

"Clear `stylesheet["background"]`" means: parse `cue.stylesheet` with `css_to_dict`, delete the `"background"` key (preserving any other CSS the user has — `color`, `font-size`), re-serialize with `dict_to_css`, assign back. Helpers already exist in `lisp/ui/ui_utils.py`.

- User clicks a swatch → write `cue.color_name = "Red"` AND clear the `background` key from `cue.stylesheet` (commit fully to themed mode; no stale custom hex).
- User clicks "No color" → clear `cue.color_name` AND clear the `background` key from `cue.stylesheet`.
- User clicks a swatch on a cue that previously had a legacy custom hex → the cue graduates to themed mode (legacy hex is dropped). User-initiated, not automatic.

**Picker ← cue read path (settings page / inspector load):**

- If `cue.color_name` is set: highlight that swatch.
- Else if `stylesheet["background"]` is set: no swatch selected; show "custom: #aabbcc" annotation.
- Else: highlight "No color".

## Data flow

### Theme application (startup)

```
main.py
  → app_conf["theme.theme"]  (e.g. "Light")
  → themes.get_theme("Light")  → Light()
  → Light().apply(qt_app)
      → BaseTheme.apply():
          → builds QPalette from Light.Colors
          → qt_app.setPalette(...)
          → themes._active = self
          → (no QssPath; QSS step skipped)
```

### Cue render (per repaint)

```
list_view.__updateItemStyle(item)
  → cue_background_hex(item.cue)
      → if cue.color_name: themes.cue_color_hex(cue.color_name) → "#C03A2A"
      → else: css_to_dict(cue.stylesheet).get("background", "")
  → QColor(hex)  → QBrush  → item paint
```

### Picker interaction (cue settings page)

```
load:
  cue_general.loadSettings(cue)
    → if cue.color_name: colorPalette.setColor(cue.color_name)
    → elif legacy_hex: colorPalette.setCustomHex(legacy_hex)
    → else: colorPalette.setColor("")

user clicks "Red" swatch:
  → CueColorPalette.colorPicked.emit("Red")
  → cue_general/inspector commit handler:
      → cue.color_name = "Red"
      → stylesheet = remove "background" key from cue.stylesheet
```

## Error handling and validation

- **`ThemeColors` validation** — bad cue palette dict (missing names, extra names, malformed hex) raises `ValueError` at theme class definition time. Catches typos before runtime. The existing exception handler in `lisp/main.py:138` then logs and falls through to no theme.
- **Missing QSS file** — already wrapped in `try/except` at `lisp/main.py`. No change. `_active` is set before QSS load so cue colors still resolve correctly.
- **Unknown `cue.color_name` at runtime** — `cue_color_hex()` falls back to `""` (no color) rather than raising. Defensive against hand-edited session files.
- **Bad legacy hex in `stylesheet["background"]`** — `QColor()` accepts CSS color names as well as hex strings; existing behavior is preserved (current code does `QColor(css_bg)` directly). No change.

## Testing

Tests live in `tests/ui/themes/` (new directory) and `tests/cues/` (existing).

1. **`test_themes.py::test_dark_palette_unchanged`** — call `Dark().apply(app)`, snapshot every `QPalette` role color. Compare to a frozen reference dict captured pre-migration. **This is the linchpin** — it de-risks the Dark refactor by proving the migrated palette is byte-equal to today's.
2. **`test_themes.py::test_light_applies_without_error`** — `Light().apply(app)`; assert no exception, `themes._active is light_instance`, key palette roles match the spec values.
3. **`test_themes.py::test_system_pass_through`** — `System().apply(app)`; assert `qt_app.palette()` is unchanged from a recorded baseline before the call.
4. **`test_themes.py::test_themecolors_validates_palette`** — pass a `cue_palette` missing "Yellow", assert `ValueError`. Pass a malformed hex (`"red"`, `"#ABC"`), assert `ValueError`.
5. **`test_themes.py::test_cue_color_hex_resolution`** — apply Dark, assert `cue_color_hex("Red") == "#C03A2A"`. Apply a fixture theme with a Solarized-style palette, assert `cue_color_hex("Red")` returns the Solarized hex.
6. **`test_themes.py::test_cue_color_hex_no_active_theme`** — without applying any theme, assert `cue_color_hex("Red")` returns the default hex (fallback path).
7. **`test_cue_color_palette.py::test_picker_emits_name`** — instantiate the widget, programmatically click a swatch, assert `colorPicked` emits the name string ("Red"), not the hex.
8. **`test_cue_color_palette.py::test_picker_legacy_custom_hex`** — call `setCustomHex("#aabbcc")`, assert no swatch is selected and the annotation is set.
9. **`test_cue.py::test_cue_color_name_property`** — round-trip a cue with `color_name="Blue"` through the property serialization; assert it loads back unchanged.
10. **`test_cue.py::test_render_priority`** — cue with both `color_name="Red"` and `stylesheet="background: #aabbcc"`. Apply Dark. Assert `cue_background_hex(cue)` returns `#C03A2A` (themed wins). Clear `color_name`, assert it returns `#aabbcc` (legacy fallback).

The first test (Dark palette snapshot) runs before any other test that mutates the application palette and is the gate for the refactor.

## Phasing

Two independent phases:

**Phase 1 — Theme infrastructure & Light theme.**
1. Add `themes/base.py` (`ThemeColors`, `BaseTheme`, validation).
2. Add `themes/__init__.py` helpers (`cue_color_hex`, `cue_palette`, `_active` tracking).
3. Migrate `themes/dark/dark.py` to subclass `BaseTheme`.
4. Add `themes/light/light.py` and `themes/system/system.py`.
5. Tests 1–6 above.

After Phase 1 the user has a real Light theme. The cue picker and rendering still use the legacy hex path; nothing about cue colors changes.

**Phase 2 — Cue color refactor.**
1. Add `color_name` property to `Cue`.
2. Update `CueColorPalette` widget (name-keyed, ring colors from `QPalette`, `setCustomHex`).
3. Update render sites (`list_view`, `playing_widgets`, optional `cart_layout`).
4. Update picker write path (`cue_general`, `commit.py`).
5. Tests 7–10 above.

Phase 2 only depends on Phase 1's `cue_color_hex()` helper. They can ship as separate PRs / branches.

## Future work (not in this design)

- **Solarized Light, Solarized Dark.** With this infrastructure each is a ~20-line file declaring base palette + `cue_palette` dict. The 7 canonical names map to Solarized accents (Solarized's magenta/cyan don't get their own picker slots; they fold into Purple/Blue or are simply unused).
- **Live theme switching.** Re-applying a theme without restart would require `apply()` to also tear down any previously-installed QSS and notify widgets to re-derive paint colors. Possible but out of scope.
- **Theme-aware QSS for Light.** Light currently ships palette-only. A QSS port would need light variants of the dark theme's resource PNGs (checkbox indicators, scrollbar arrows in `themes/dark/assets/`). Tracked separately.
- **Per-theme cue color palettes for Dark and Light.** Both currently share `DEFAULT_CUE_PALETTE`. If a future user-research finding indicates the existing 7 hexes don't read well on light backgrounds, Light can override `cue_palette` without affecting Dark.
