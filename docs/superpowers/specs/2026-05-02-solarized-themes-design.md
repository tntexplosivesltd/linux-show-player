# Solarized Light & Dark Themes — Design

**Date:** 2026-05-02
**Status:** Draft

## Goal

Add `SolarizedDark` and `SolarizedLight` themes alongside the existing `Dark`, `Light`, and `System` themes. Both adopt Ethan Schoonover's Solarized palette ([ethanschoonover.com/solarized](https://ethanschoonover.com/solarized)). The themes reuse the existing `dark/theme.qss` and `light/theme.qss` stylesheets verbatim — visual fidelity comes from `QPalette` substitution. A targeted QSS retuning pass is planned as a separate follow-up phase, scheduled once the palette-only result can be eyeballed.

A small expansion of the `ThemeColors` contract introduces a theme-driven **standby indicator colour**, replacing the hardcoded `QBrush(QColor(250, 220, 0, 100))` class constant in `CueListView`. Dark and Light keep that exact value; Solarized themes provide Solarized magenta `#D33682` at α 100.

## Non-Goals

- Porting/retuning `dark/theme.qss` or `light/theme.qss` for Solarized fidelity. Phase 1 ships palette-only via QSS reuse. Targeted overrides for off-palette hex values inside the existing QSS files (`#80AAD5`, `#404858`, `#626873`, etc.) are deferred to a later follow-up.
- Adding any other Solarized-flavoured chrome assets (checkbox indicators, scrollbar arrows in `themes/dark/assets/`). The Solarized themes inherit these from the underlying Dark/Light QSS.
- Live theme switching at runtime. `apply()` continues to run once at startup; theme changes still require restart.
- Adding new cue colour names. The 7-name palette (`Red, Orange, Yellow, Green, Blue, Purple, Grey`) is unchanged; Solarized themes only remap the hex values for those 7 names.
- Reworking other hardcoded UI-state colours that are not the standby indicator (e.g. `GROUP_OUTLINE_PARALLEL/PLAYLIST` in `list_view.py:123-124`, the status border colours in `theme.qss` running/pause/error rules). These are out of scope; a future spec can address them as a unit.
- Theme-name translation. Class names `SolarizedDark` and `SolarizedLight` appear directly in the settings dropdown, matching the existing pattern (`Dark`, `Light`, `System`).

## Palette

Solarized's 16-tone reference palette ([Schoonover, 2011](https://ethanschoonover.com/solarized/#the-values)):

| Role          | Hex       | Role          | Hex       |
|---------------|-----------|---------------|-----------|
| base03 (bg₋)  | `#002B36` | yellow        | `#B58900` |
| base02 (bg₋₊) | `#073642` | orange        | `#CB4B16` |
| base01 (fg₋)  | `#586E75` | red           | `#DC322F` |
| base00 (fg₋₊) | `#657B83` | magenta       | `#D33682` |
| base0 (fg)    | `#839496` | violet        | `#6C71C4` |
| base1 (fg₊)   | `#93A1A1` | blue          | `#268BD2` |
| base2 (bg₊₋)  | `#EEE8D5` | cyan          | `#2AA198` |
| base3 (bg₊)   | `#FDF6E3` | green         | `#859900` |

Every Solarized accent is assigned exactly one role across the two themes — no accent serves two roles.

### Role assignment

| Solarized accent | Role                              |
|------------------|-----------------------------------|
| red `#DC322F`    | Cue colour `Red` + `bright_text`  |
| orange `#CB4B16` | Cue colour `Orange`               |
| yellow `#B58900` | Cue colour `Yellow`               |
| green `#859900`  | Cue colour `Green`                |
| blue `#268BD2`   | Cue colour `Blue`                 |
| violet `#6C71C4` | Cue colour `Purple`               |
| cyan `#2AA198`   | `highlight` (selection wash)      |
| magenta `#D33682`| `standby_indicator` (UI state)    |

`Grey` cue colour uses Solarized base tones, not an accent: `base01 #586E75` (Dark) / `base1 #93A1A1` (Light).

### `SolarizedDark` ThemeColors

```python
ThemeColors(
    background=QColor("#002B36"),       # base03
    foreground=QColor("#073642"),       # base02 — chrome
    text=QColor("#839496"),             # base0
    highlight=QColor("#2AA198"),        # cyan
    alternate_base=QColor("#073642"),   # base02 — list striping
    highlighted_text=QColor("#FDF6E3"), # base3 — text on cyan selection
    bright_text=QColor("#DC322F"),      # red — Solarized's bright_text role
    standby_indicator=QColor(211, 54, 130, 100),  # magenta @ α 100
    cue_palette={
        "Red":    "#DC322F",
        "Orange": "#CB4B16",
        "Yellow": "#B58900",
        "Green":  "#859900",
        "Blue":   "#268BD2",
        "Purple": "#6C71C4",
        "Grey":   "#586E75",  # base01
    },
    cue_alpha=150,  # match Dark
)
```

### `SolarizedLight` ThemeColors

```python
ThemeColors(
    background=QColor("#FDF6E3"),       # base3
    foreground=QColor("#EEE8D5"),       # base2 — chrome
    text=QColor("#657B83"),             # base00
    highlight=QColor("#2AA198"),        # cyan
    alternate_base=QColor("#EEE8D5"),   # base2 — list striping
    highlighted_text=QColor("#FDF6E3"), # base3 — text on cyan selection
    bright_text=QColor("#DC322F"),      # red
    standby_indicator=QColor(211, 54, 130, 100),  # magenta @ α 100
    cue_palette={
        "Red":    "#DC322F",
        "Orange": "#CB4B16",
        "Yellow": "#B58900",
        "Green":  "#859900",
        "Blue":   "#268BD2",
        "Purple": "#6C71C4",
        "Grey":   "#93A1A1",  # base1
    },
    cue_alpha=220,  # match Light
)
```

The cue accent values (`Red` through `Purple`) are identical in both themes — Solarized's design intent is that accents read at equal perceived lightness against either base. Only `Grey` and the chrome tones differ.

## Standby indicator — theme contract expansion

### Today

`lisp/plugins/list_layout/list_view.py:119` defines:

```python
ITEM_CURRENT_BG = QBrush(QColor(250, 220, 0, 100))
```

This brush is applied at `list_view.py:506-508` when a list item is the standby cue (`item.current is True`); it **replaces** any cue colour the row would otherwise paint (the `if item.current: ... else: hex_bg = ...` branch in `__updateItemStyle`). A standby row therefore renders as a solid band of the standby colour regardless of the cue's own `color_name`. The hex `#FADC00` is theme-independent — every theme renders standby in the same warm sticky-note yellow.

### Change

Add an optional `standby_indicator` field to `ThemeColors`:

```python
@dataclass(frozen=True)
class ThemeColors:
    # ... existing fields ...
    standby_indicator: Optional[QColor] = None
```

Add a helper to `lisp/ui/themes/__init__.py`:

```python
DEFAULT_STANDBY_INDICATOR = QColor(250, 220, 0, 100)

def standby_indicator() -> QColor:
    """Return the active theme's standby indicator color.

    Falls back to the legacy hardcoded yellow when no theme is active
    or the active theme has no ``Colors``.
    """
    if _active is not None and hasattr(_active, "Colors"):
        c = _active.Colors.standby_indicator
        if c is not None:
            return c
    return DEFAULT_STANDBY_INDICATOR
```

Refactor `list_view.py`:
- Delete the `ITEM_CURRENT_BG` class constant.
- Replace the `brush = CueListView.ITEM_CURRENT_BG` line with `brush = QBrush(themes.standby_indicator())`. The brush is constructed at paint time, so the value is read live (matters only if we later add live theme switching — does no harm today).

`Dark` and `Light` do not declare `standby_indicator` — they fall through to the legacy default. Visually unchanged.

`SolarizedDark` and `SolarizedLight` declare `standby_indicator=QColor(211, 54, 130, 100)` (magenta `#D33682` α 100).

### Why magenta

In the Solarized palette, magenta is the only accent not consumed by either a cue colour or the selection highlight. Using it for the standby indicator gives every Solarized accent exactly one role.

Because the standby brush replaces the cue colour rather than blending with it, the painting code does not produce hue mixtures — a standby row paints as solid magenta α 100, not magenta-over-violet or magenta-over-red. The relevant readability question is therefore not "do hue X and hue Y blend cleanly" but rather "is the standby band visually distinct from any cue colour the operator might also see in the same list?" Magenta has the largest hue distance from all six chromatic cue colours (≥ ~30° from Purple/violet, ≥ 60° from the others), so a standby row never reads as "just another instance of cue colour Z."

This decision is intentionally cheap to revisit: the value lives as a one-line `QColor(...)` in each Solarized theme file and can be retuned without touching `list_view.py` or any other code.

## File layout

Mirror the existing `dark/` and `light/` directories. The `assets/` and `assets.py` machinery in `dark/` (icons, scrollbar arrows, checkbox indicators) is shared with `light/` via no-import-of-assets in `light.py` — Solarized themes follow Light's pattern: don't import the asset module, let the underlying QSS reference the dark assets where needed.

```
lisp/ui/themes/
├── base.py                        # add `standby_indicator` field
├── __init__.py                    # add `standby_indicator()` helper
├── dark/
│   ├── dark.py
│   └── theme.qss
├── light/
│   ├── light.py
│   └── theme.qss
├── solarized_dark/                # NEW
│   ├── __init__.py
│   └── solarized_dark.py
└── solarized_light/               # NEW
    ├── __init__.py
    └── solarized_light.py
```

Each Solarized theme file is ~30 lines: imports, GPLv3 header, `ThemeColors` declaration, `QssPath` pointing to the corresponding existing QSS:

```python
class SolarizedDark(BaseTheme):
    Colors = ThemeColors(...)  # see above
    QssPath = os.path.join(
        os.path.dirname(__file__), "..", "dark", "theme.qss"
    )
```

`SolarizedLight` similarly references `../light/theme.qss`.

The `load_classes` discovery in `lisp/ui/themes/__init__.py:14` picks up the new directories automatically; no registration changes needed.

## Validation

- `ThemeColors.__post_init__` already validates `cue_palette` keys and hex format. The new `standby_indicator` field is `Optional[QColor]` — no extra validation needed (Qt's `QColor` constructor handles its own input).
- `cue_alpha` validation (0-255) applies as today.

## Testing

Unit tests (`tests/ui/themes/`):

1. **Theme load smoke test** — `tests/ui/themes/test_solarized_themes.py`:
   - Instantiate `SolarizedDark()` and `SolarizedLight()`.
   - Assert each `Colors` is a valid `ThemeColors` (no exception from `__post_init__`).
   - Assert `cue_palette` has exactly the 7 canonical keys.
   - Assert all hex values match `^#[0-9A-Fa-f]{6}$`.
   - Assert `standby_indicator` is non-None and a `QColor` with α 100.

2. **Theme discovery** — extend the existing themes-discovery test (or add one if absent) to assert `themes_names()` returns both new theme names.

3. **`standby_indicator()` helper** — `tests/ui/themes/test_standby_indicator.py`:
   - Assert default value when no theme active.
   - Assert Dark and Light fall through to default (legacy yellow).
   - Assert SolarizedDark/Light return magenta α 100.

No E2E tests required: the standby colour change is a paint-time substitution and is covered by the unit test on the helper plus visual inspection during phase 4.

## Phasing

1. **Phase 1 — `ThemeColors.standby_indicator` + helper.** Add the optional field; add `themes.standby_indicator()` and `DEFAULT_STANDBY_INDICATOR`. No callers yet. Tests for the helper. Existing themes unchanged.

2. **Phase 2 — `list_view.py` refactor.** Replace the `ITEM_CURRENT_BG` constant with the runtime `themes.standby_indicator()` lookup. Visual no-op on Dark/Light. Manual smoke test: launch on Dark, confirm standby is the same yellow as before.

3. **Phase 3 — Solarized theme files.** Add `solarized_dark/` and `solarized_light/` directories with their `BaseTheme` subclasses. Add unit tests. Solarized themes appear in the settings dropdown.

4. **Phase 4 — Visual smoke test.** Launch LiSP on each Solarized theme, exercise: cue list with mixed cue colours and uncoloured rows (alt-row striping visible), selection (cyan wash), standby (magenta band), grouped cues (parallel/playlist outlines remain their current green/orange — out of scope here), running/pause/error states on `ListTimeWidget`, cart layout cells, settings dialogs.

5. **Phase 5 — Worktree QA + code review (mandatory).** Spawn voltagent qa-expert and code-reviewer subagents on the worktree before merge.

QSS retuning is **not in this spec.** It will be a separate spec (and PR) once Phase 4 surfaces concrete chrome details that fight the Solarized base tones.

## Risks

- **QSS hex values fight the palette.** `dark/theme.qss` contains hardcoded `#80AAD5` (info-toast accent), `#404858`/`#5a6a80` (slate panels), `#626873` (a chrome accent), and several others. Against Solarized's deep teal `base03`, these will read as visually off — but only in chrome corners (toasts, splitters, secondary panels). Cue list, cart, and main views are palette-driven and will look right. Risk is cosmetic, mitigated by the planned Phase-1.5 retuning spec.
- **Standby/Purple visual proximity.** Magenta and violet are ~30° apart in hue — the smallest hue distance in the cue-colour matrix. Standby renders as solid magenta α 100 (not blended with the cue), but a standby row sitting *adjacent* to a Purple-coloured cue row still presents two pinkish-purple bands of differing saturation. If this proves hard to scan at a glance during Phase 4, the standby colour can be changed in one line per theme. Documented in Phase 4 acceptance criteria.
- **`standby_indicator` API drift.** Future themes (third-party or built-in) might forget to set `standby_indicator` and inherit the legacy `#FADC00` yellow on a Solarized-style palette. Acceptable — the optional default is "no worse than today."

## Acceptance criteria

- `themes_names()` returns `["Dark", "Light", "System", "SolarizedDark", "SolarizedLight"]` (order not asserted).
- Selecting `SolarizedDark` or `SolarizedLight` in settings and restarting yields a Solarized-coloured UI: base03/base3 backgrounds, base02/base2 list striping, cyan selection, magenta standby band, and the 7 cue colours rendered with the Solarized hexes.
- `Dark` and `Light` themes are byte-equivalent in behaviour to before this change. Standby on `Dark`/`Light` renders as the same `#FADC00` α 100 yellow.
- All new unit tests pass.
- Phase 5 review subagents return with no high-confidence findings.
