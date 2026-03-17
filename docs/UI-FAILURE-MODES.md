# UI Failure Modes — What Goes Wrong

A comprehensive catalog of UI bugs we need to detect automatically. Each failure mode needs a detection strategy.

## 1. RENDERING FAILURES

| Failure | Description | Detection Strategy |
|---------|-------------|-------------------|
| **Black screen** | Page loads but nothing renders (JS crash, WebGL fail, module import error) | `is_mostly_black()` — >90% dark pixels |
| **White screen** | Blank white page (server error, HTML not served) | Mean brightness >240, no colored pixels |
| **Partial render** | Some elements render, others don't (race condition, async load fail) | Compare element count vs expected minimum |
| **Flicker/flash** | Elements appear and disappear rapidly | Video analysis: high change frequency in same region |
| **Layout thrash** | Elements resize continuously (infinite layout loop) | Video analysis: element bounds oscillate |

## 2. ELEMENT OVERLAP

| Failure | Description | Detection Strategy |
|---------|-------------|-------------------|
| **Z-index war** | Two elements fight for the same space (dropdowns behind headers) | In semantic render mode: check for overlapping bounding boxes at same z-level |
| **Panel pile-up** | Multiple panels open at exact same position | Detect 3+ panels with center points within 20px |
| **Toast overlap** | Notifications cover interactive elements | Check toast z-region doesn't intersect with button z-region |
| **Corner crowding** | Too many elements in one screen corner | Divide screen into quadrants, count elements per quadrant |
| **Overflow clipping** | Content extends past container (scrollbars appear, text cut off) | Detect content that extends to screen edge without margin |

## 3. INTERACTIVE FAILURES

| Failure | Description | Detection Strategy |
|---------|-------------|-------------------|
| **Dead button** | Button exists but click does nothing | Click → screenshot before/after → `detect_changes()` should show change |
| **Dead toggle** | Checkbox/toggle doesn't change state | Toggle → read state → should differ from before |
| **Dead close button** | Panel close button doesn't close the panel | Click close → panel should disappear from DOM |
| **Menu blocked** | Dropdown opens but is behind another element | Open menu → screenshot → detect menu items visible (not occluded) |
| **Drag broken** | Panel drag handle doesn't move the panel | Drag → compare position before/after |

## 4. VISUAL QUALITY

| Failure | Description | Detection Strategy |
|---------|-------------|-------------------|
| **Text unreadable** | Text too small, wrong color, or on wrong background | OCR confidence score or contrast ratio check |
| **Icon missing** | Empty space where icon should be | Detect blank rectangles in expected icon positions |
| **Color wrong** | Element renders in wrong color (CSS variable not resolved) | Sample pixel color at known element, compare to expected |
| **Alignment off** | Elements not aligned to grid/each other | Edge detection + line fitting, check alignment |
| **Font fallback** | Wrong font loaded (system font instead of monospace) | Character width analysis (monospace = uniform width) |

## 5. STATE CONSISTENCY

| Failure | Description | Detection Strategy |
|---------|-------------|-------------------|
| **Stale data** | UI shows old data (WebSocket disconnected, no refresh) | Compare displayed values to API response |
| **Counter wrong** | Target count, alert count doesn't match actual data | Read HUD counter → compare to API endpoint |
| **Status indicator wrong** | "Connected" shown when disconnected | Check WebSocket state vs displayed indicator |
| **Layer state mismatch** | Layer checkbox says ON but layer not visible on map | Toggle layer → `detect_changes()` should show map change |
| **Filter not applied** | Filter dropdown changed but display unchanged | Change filter → screenshot → compare to pre-filter |

## 6. PERFORMANCE ISSUES

| Failure | Description | Detection Strategy |
|---------|-------------|-------------------|
| **Low FPS** | Application runs below 30fps | Read FPS counter from HUD, or measure frame delivery rate |
| **Memory leak** | Performance degrades over time | FPS trend analysis over 60+ seconds |
| **Animation stutter** | Smooth animation becomes jerky | Frame-to-frame timing analysis (std dev of frame intervals) |
| **Load time** | Page takes >5s to become interactive | Time from navigation to first meaningful paint |
| **Unresponsive** | UI freezes completely | No frame changes for >2 seconds during active simulation |

## 7. LAYOUT FAILURES

| Failure | Description | Detection Strategy |
|---------|-------------|-------------------|
| **Responsive break** | Elements misaligned at certain viewport sizes | Run at multiple viewport sizes, compare layouts |
| **Scroll broken** | Content exists but can't be scrolled to | Check if elements extend beyond viewport without scrollbar |
| **Panel off-screen** | Panel dragged or spawned outside visible area | Check all panel positions are within viewport bounds |
| **Resize handle missing** | Panel can't be resized | Check for resize handle element in DOM |
| **Minimap wrong** | Minimap doesn't match actual map view | Compare minimap content to main view (scaled) |

## Priority Detection Order

When running automated UI checks, test in this order:
1. **Black screen?** — if yes, everything else is pointless
2. **JS errors?** — catch crashes before they cascade
3. **Element count** — are the expected panels/markers present?
4. **Overlap check** — are elements fighting for space?
5. **Interactive check** — do buttons/toggles actually work?
6. **Visual quality** — colors, text, alignment correct?
7. **Performance** — FPS acceptable?
8. **State consistency** — data matches backend?
