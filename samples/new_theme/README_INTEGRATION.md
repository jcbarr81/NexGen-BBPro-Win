# NexGen BBPro — UI Graphics Asset Bundle
# ─────────────────────────────────────────────────────────────────────────

## Files in this bundle

| File                  | Description                                              |
|-----------------------|----------------------------------------------------------|
| `theme_enhanced.py`   | Drop-in replacement for `theme.py` — enhanced warm theme |
| `theme_newspaper.py`  | New alternate theme — newspaper/print editorial style    |
| `icons.svg`           | 16 nav + action button icons (sidebar & Quick Actions)   |
| `dividers.svg`        | Decorative dividers, card headers, button shapes         |

---

## 1. Swapping in the Enhanced Warm Theme

Replace your existing `ui/theme.py` with `theme_enhanced.py`, or import
from it. No other code changes needed — all existing object names are preserved.

```python
# In main.py or wherever you apply the stylesheet:
from ui.theme_enhanced import ENHANCED_DARK_QSS, ENHANCED_LIGHT_QSS
app.setStyleSheet(ENHANCED_DARK_QSS)   # or ENHANCED_LIGHT_QSS
```

**What's improved vs the original:**
- Sidebar NavButtons have a 3px amber left-accent bar when active
- NavButtons show a subtle gradient reveal on hover instead of a flat fill
- Quick Action / Roster buttons use a raised "dugout tile" gradient with a
  top highlight and bottom shadow — much more tactile, matching the splash
- Section titles get an amber underline for hierarchy
- MetricValue numbers are larger (26px → 26px bold 900 weight) and use
  amber on dark mode for dashboard energy
- New `#ActionButton` object name — assign this to your Quick Actions grid
  buttons and roster page buttons to get the improved tile style

**To use #ActionButton on existing buttons:**
```python
btn.setObjectName("ActionButton")
```

---

## 2. Adding the Newspaper Theme

Copy `theme_newspaper.py` into `ui/`. Add a theme selector to your
settings or Toggle Theme button:

```python
from ui.theme_newspaper import NEWSPAPER_DARK_QSS, NEWSPAPER_LIGHT_QSS
from ui.theme_enhanced  import ENHANCED_DARK_QSS, ENHANCED_LIGHT_QSS

THEMES = {
    "Warm Dark":       ENHANCED_DARK_QSS,
    "Warm Light":      ENHANCED_LIGHT_QSS,
    "Press (Dark)":    NEWSPAPER_DARK_QSS,
    "Newsprint (Light)": NEWSPAPER_LIGHT_QSS,
}

def apply_theme(name: str) -> None:
    QApplication.instance().setStyleSheet(THEMES[name])
```

**Newspaper theme characteristics:**
- Font switches to Georgia / Times New Roman (serif) for display text
- Monospace Courier New for labels and stats — typewriter feel
- Buttons are outlined ink-style (no fill), invert on hover
- Sidebar uses a black background with red left-accent bars
- Cards have square corners and double-ruled borders
- Red (#C8102E) used only for accent/active states — like a stamp or
  headline ink, never as a fill

---

## 3. SVG Icons (icons.svg)

The `icons.svg` file contains `<symbol>` elements for the sidebar nav icons
and standalone `<svg>` elements for action button icons.

### Using nav icons in PyQt6

```python
from PyQt6.QtSvgWidgets import QSvgWidget

def make_nav_icon(symbol_id: str, size: int = 18) -> QSvgWidget:
    # Extract symbol and wrap in a standalone SVG
    svg_content = f'''<svg xmlns="http://www.w3.org/2000/svg"
        width="{size}" height="{size}" viewBox="0 0 24 24"
        fill="none" stroke="rgba(255,253,240,0.75)"
        stroke-width="1.8" stroke-linecap="round">
      <use href="icons.svg#{symbol_id}"/>
    </svg>'''
    widget = QSvgWidget()
    widget.load(svg_content.encode())
    return widget
```

Available symbol IDs:
  - `icon-dashboard`   — grid of four squares
  - `icon-roster`      — two people silhouette
  - `icon-team`        — group silhouette
  - `icon-records`     — bar chart
  - `icon-trades`      — swap arrows
  - `icon-league`      — globe
  - `icon-admin`       — star badge

### Using action button icons

Each action button SVG is a standalone `<svg>` element with an `id`.
Load them as QPixmap and place beside button text, or use as
`background-image` in QSS:

```python
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtGui import QPixmap, QPainter

def svg_icon_pixmap(icon_id: str, size: int = 20, color: str = "#fffdf0") -> QPixmap:
    # Read icons.svg, find the matching element, recolor and render
    renderer = QSvgRenderer(f"assets/graphics/icons.svg")
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    return pixmap
```

Available action icon IDs:
  - `btn-lineups`       — list with magnifier
  - `btn-transactions`  — swap arrows
  - `btn-stats`         — bar chart
  - `btn-depth`         — org tree
  - `btn-settings`      — gear / cog
  - `btn-injuries`      — medical cross
  - `btn-schedule`      — calendar
  - `btn-standings`     — trophy
  - `btn-playoffs`      — star
  - `btn-draft`         — person with down arrow
  - `btn-leaders`       — group with crown

---

## 4. Decorative Dividers (dividers.svg)

The `dividers.svg` file contains reference shapes for each theme.
Use as:

**In QSS (as a border-image):**
```css
QFrame#SectionDivider {
    border-image: url(assets/graphics/divider_warm.svg) 0 0 0 0 stretch stretch;
    min-height: 12px;
    max-height: 12px;
}
```

**Named elements available:**
  - `divider-warm`                  — amber diamond + ruled lines
  - `card-header-warm`              — brown gradient header strip
  - `stat-tile-warm`                — raised metric tile shape
  - `action-btn-warm`               — action button tile shape
  - `nav-item-active-warm`          — sidebar active state shape
  - `divider-newspaper-light`       — double ink rule + ornament
  - `card-header-newspaper-light`   — black ink header
  - `action-btn-newspaper-light`    — outlined ink button
  - `nav-item-active-newspaper`     — red-accented nav item
  - `divider-newspaper-dark`        — white rule on black

---

## 5. Recommended file placement

```
NexGen-BBPro/
  ui/
    theme.py              ← keep original as backup
    theme_enhanced.py     ← NEW: drop in here
    theme_newspaper.py    ← NEW: drop in here
  assets/
    graphics/
      icons.svg           ← NEW
      dividers.svg        ← NEW
      golden/             ← existing
```

---

## Quick start (minimal change)

1. Copy `theme_enhanced.py` → `ui/theme_enhanced.py`
2. In `main.py`, change the import:
   ```python
   # from ui.theme import DARK_QSS          # old
   from ui.theme_enhanced import DARK_QSS    # new
   ```
3. For the dashboard Quick Action buttons, add one line per button:
   ```python
   btn_lineups.setObjectName("ActionButton")
   btn_transactions.setObjectName("ActionButton")
   # ... etc
   ```
4. Run the app — the sidebar and action buttons will immediately look improved.
