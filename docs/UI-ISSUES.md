# UI Issues — Known Problems and Planned Fixes

## Layout Overlaps

| Issue | Location | Status | Priority |
|-------|----------|--------|----------|
| Menu dropdowns blocked by header bar | Top | FIXED (z-index) | — |
| Toasts overlapped alerts panel | Top-right | FIXED (moved to bottom-right) | — |
| Legend overlaps patrol draw buttons | Bottom-left | Open | HIGH |
| Compass overlaps legend | Bottom-left | Open | HIGH |
| Elements overlap in top-left | Top-left | Open | MEDIUM |

## Panel Issues

| Issue | Status | Priority |
|-------|--------|----------|
| Close button too dim/small | FIXED (border + larger font) | — |
| Fusion pipeline close doesn't work | Open — needs investigation | HIGH |
| Satellite toggle doesn't work in Layers panel | Open — toggle mechanism issue | HIGH |
| Some layers can't be toggled | Open — missing mapActions function | MEDIUM |
| Layer names need improvement | Open | LOW |

## Proposed: Map Toolbar

A collapsible vertical button palette on the left side of the screen for all map interactions:

```
┌──┐
│🧭│ Compass (toggle)
│📍│ Draw geofence
│🛤│ Draw patrol route
│📏│ Measure distance
│📷│ Screenshot
│🔍│ Search
│⚙│ Map settings
│ ↕│ Expand/collapse
└──┘
```

Features:
- Vertical strip, left edge of map
- Each button is an icon + tooltip
- Collapse to just icons (default) or expand to show labels
- Click to activate tool, click again to deactivate
- Currently active tool highlighted
- Replaces scattered bottom-left buttons and compass
- Compass becomes a dedicated section at top of toolbar (always visible, rotates with camera)

## Style Guidelines

- All buttons: cyberpunk aesthetic (dark bg, cyan border, glow on hover)
- Icons: simple Unicode/emoji or SVG
- Font: monospace
- Z-index: 50 (above map, below panels)
- Width: 40px collapsed, 140px expanded
- Position: left edge, vertically centered
