# UI Layout Zone System

## Problem

Elements overlap because there's no systematic zone allocation. Multiple components claim the same screen corner.

## Zone Map

```
┌──────────────────────────────────────────────────────────┐
│ MENU BAR (fixed top, full width, z:200)                  │
├──────────────┬────────────────────────┬──────────────────┤
│ TOP-LEFT     │ TOP-CENTER             │ TOP-RIGHT        │
│              │                        │                  │
│ • Sidebar    │ • Layer HUD            │ • Alerts panel   │
│ • Panel list │ • Welcome tooltip      │ • Kill feed      │
│              │ • Banners              │                  │
├──────────────┤                        ├──────────────────┤
│              │                        │                  │
│              │      MAP CANVAS        │                  │
│              │                        │                  │
│              │  (panels float above)  │                  │
│              │                        │                  │
├──────────────┤                        ├──────────────────┤
│ BOTTOM-LEFT  │ BOTTOM-CENTER          │ BOTTOM-RIGHT     │
│              │                        │                  │
│ • Minimap    │ • Controls hint        │ • Toasts         │
│ • Legend     │ • Patrol draw HUD      │ • Gamepad        │
│              │ • Geofence prompt      │                  │
└──────────────┴────────────────────────┴──────────────────┘
```

## Zone Rules

1. **Each zone has a max of 2-3 elements** stacked vertically
2. **Panels** are floating windows — NOT in zones (they have their own z-index and dragging)
3. **Toasts** go to BOTTOM-RIGHT (below panels, above gamepad indicator)
4. **Alerts panel** occupies TOP-RIGHT as a floating panel (draggable)
5. **Minimap** occupies BOTTOM-LEFT
6. **No element should overlap another in the same zone** — stack them vertically with padding

## Current Overlaps to Fix

| Zone | Overlap | Fix |
|------|---------|-----|
| TOP-RIGHT | Alerts panel + old toast position | FIXED: toasts moved to bottom-right |
| BOTTOM-LEFT | Minimap + legend + patrol draw buttons | Need: stack vertically, minimap on top |
| TOP-LEFT | Sidebar + panel cascade start position | Need: panels start below sidebar |
| BOTTOM-RIGHT | Toasts + controls hint + gamepad | Need: toasts above controls hint |

## Z-Index Hierarchy

| Layer | z-index | Elements |
|-------|---------|----------|
| Modals | 1000+ | Game over, mission select, lightbox |
| Context menu | 500 | Right-click map menu |
| Menu bar | 200 | Top menu bar + dropdowns |
| Toasts | 150 | Notification toasts |
| Panels | 100 | All floating panels |
| Map overlays | 10 | Layer HUD, filter overlay, kill feed |
| Map | 0 | MapLibre + Three.js canvas |
