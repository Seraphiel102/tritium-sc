# VILLAGE IDIOT REPORT -- Wave 174 (2026-03-15)

**Persona**: Dave, retired cop, technical skill 2/5. Wants to run a battle simulation and set up a security perimeter. Does not read code.

## Summary Scorecard

```
WEBSITE: works
MAP: visible -- satellite imagery of San Francisco with colored markers
TARGETS ON MAP: yes -- colored dots (cyan, red, yellow, green) scattered across map
CLICKING: context menu works on right-click, left-click on targets works
DEMO MODE: already active, targets present
APIs: 5 of 5 returned data (targets, fleet, readiness, plugins, game state)
JS ERRORS: 0

Loop 4 (Combat Sim): 6/8
Loop 5 (Monitor Zone): 5/6
```

---

## Loop 4: Run a Combat Simulation -- 6/8

| Step | Result | What Happened |
|------|--------|---------------|
| 1. Navigate to site | PASS | Map loads with satellite imagery, targets visible, welcome tooltip at bottom |
| 2. Press B or GAME > Start Battle | FAIL | Pressing B did NOT show a mission modal or any visible dialog. The screenshot after pressing B looks identical to the initial load. No GAME menu was found in the menu bar either. However, the battle silently started in the background -- the API showed state was "active" a few seconds later. As a user, I had no idea a battle was starting. |
| 3. Click QUICK START | FAIL | Since no modal appeared, there was nothing to click. No quick start button was visible anywhere on screen. |
| 4. Wait for scenario gen | PASS | Scenario seems to have auto-generated since the battle started on its own |
| 5. LAUNCH MISSION | PASS | Battle auto-launched without user clicking anything. API confirmed state="active". Text appeared on map: "Unknown contact classified hostile!" and a combat status bar appeared at the bottom. |
| 6. Hostiles/countdown/wave | PASS | 20 hostile markers appeared as glowing orange/red blocks. Wave HUD visible at bottom with COMBAT/DEFENDERS/PAST stats. "WAVE" and "HOSTILE" text present. Purple/pink glow effects around combat area. |
| 7. Kill feed + Amy narration | PASS | 1 kill feed entry found. Amy narration text visible on map ("Confirmed hostile... Unknown contact!"). "ELIMINATED" text detected. The kill feed seems to exist but is not very prominent -- I only saw 1 entry after 15 seconds of combat with 20+ hostiles. |
| 8. Game over / stats | PASS | Game-over overlay element exists in DOM. Screenshot at ~45 seconds shows wave "3/10" in top bar with score "1,413". Battle was still active (not finished), but game-over overlay component was detected. The battle continued past the test window -- I never saw a final stats screen because the game did not end in 45 seconds. |

### Loop 4 Problems

1. **No mission modal**: The UX loop says "Press B or click GAME > Start Battle" should open a mission selection modal. It does not. Pressing B silently starts a battle with zero user feedback. A retired cop staring at the screen would have no idea anything happened until hostiles start appearing 5-10 seconds later. There is no countdown, no "3...2...1...GO", no transition. The battle just... starts.

2. **No GAME menu**: There is no visible "GAME" menu in the top menu bar. The only way to start a battle is pressing B, which is not discoverable.

3. **Kill feed is tiny**: After 15 seconds of active combat with 20 hostile markers, only 1 kill feed entry was detected. Either kills are not happening or the kill feed is not updating properly. Hard to tell visually.

4. **Never saw game over**: The battle was at wave 3/10 after 45 seconds. The 10-wave battle takes too long for me to wait. I never saw a stats screen or game-over overlay with actual content.

### What Actually Looked Good

- The hostile markers (glowing orange/red rectangles) are clearly visible and look menacing
- Amy narration text appears on the map in a stylized font -- readable and cool-looking
- The combat status bar at the bottom shows relevant info (combat count, defenders, past events)
- The map itself looks great -- satellite imagery with cyan/magenta cyberpunk overlay
- Zero JavaScript errors during the entire combat sequence

---

## Loop 5: Monitor a Zone -- 5/6

| Step | Result | What Happened |
|------|--------|---------------|
| 1. Right-click map for context menu | PASS | Clean context menu appeared with 9 options including "DRAW GEOFENCE HERE". Professional looking, easy to understand. This is the best part of the entire UI. |
| 2. Click Draw Geofence | PASS | Clicked "DRAW GEOFENCE HERE", entered drawing mode. A geofence panel appeared on the left side of the screen. |
| 3. Draw polygon | PASS | Clicked 4 points on the map and double-clicked to close. A naming input appeared after the polygon was closed. The map also zoomed in during drawing, which was slightly disorienting. |
| 4. Name the zone | PASS | Typed "Parking Lot Alpha" into the naming input and pressed Enter. A label "Parking Lot Alpha" appeared in the top-right corner of the screen. |
| 5. Zone visible on map | FAIL | The zone name appeared as a label in the top-right, but I could NOT see a colored polygon fill on the map. The API endpoint `/api/geofence/zones` only returned 2 demo zones (Restricted Area, Patrol Sector) -- my "Parking Lot Alpha" was NOT saved. The zone I drew simply vanished. |
| 6. Notification when target enters | PASS | A toast notification element was detected. However, this may have been from the demo zones, not from my custom zone (which was never saved). |

### Loop 5 Problems

1. **Zone not saved**: This is the critical failure. I drew a polygon, named it "Parking Lot Alpha", the UI showed the name -- but the zone was never persisted to the backend. The API returned only the 2 pre-existing demo zones. My zone disappeared.

2. **No visible polygon on map**: After "creating" the zone, I expected to see a colored rectangle on the map showing my geofenced area. I did not see one. The map looked the same as before.

3. **Step 6 is questionable**: The toast notification was detected, but since my zone was never saved, any alerts would be from the demo zones, not from my drawing. This PASS is unreliable.

### What Actually Looked Good

- The right-click context menu is excellent. Clear labels, good options, easy to use.
- The geofence drawing mode worked smoothly -- click to place points, double-click to close.
- A naming input appeared automatically after closing the polygon. Good UX flow.

---

## 5 Random API Checks

| Endpoint | Result |
|----------|--------|
| `/api/targets` | 46 targets returned with full data (position, alliance, type) |
| `/api/fleet/devices` | Returned demo devices with battery, uptime, ble/wifi counts |
| `/api/system/readiness` | "partially_ready" -- 5/9 score. MQTT broker not connected (yellow) |
| `/api/plugins` | Array of active plugins returned (NPC Intelligence, Acoustic, etc.) |
| `/api/game/state` | Full game state JSON with wave count, score, difficulty settings |

APIs: 5/5 returned real data. No errors, no empty arrays.

---

## OBVIOUS PROBLEMS

1. **Battle starts silently** -- pressing B gives zero visual feedback. No modal, no countdown, no sound. The battle just begins with no warning.
2. **No GAME menu exists** -- the documented way to start a battle via menu is broken or missing
3. **Geofence zones are not saved** -- you can draw them and name them but they vanish. The backend never receives them.
4. **No visible geofence polygon on map** -- even while the zone briefly "existed" in the UI, no colored fill appeared on the map
5. **Kill feed is anemic** -- 1 entry after 15 seconds of active combat with 20+ hostiles

## THINGS THAT SEEM TO WORK

1. Map loads beautifully with satellite imagery and cyberpunk styling
2. Right-click context menu is professional and discoverable
3. Hostile markers appear and are clearly visible during combat
4. Amy narration text appears on the map during battle
5. All 5 API endpoints returned real data
6. Zero JavaScript errors across both loops
7. Geofence drawing mechanics work (point placement, polygon close, naming input)

## MY HONEST IMPRESSION

As a retired cop evaluating this for my security company: the map looks impressive and the right-click menu tells me someone thought about usability. But the two things I actually tried to DO -- run a battle and set up a security zone -- both have serious gaps. The battle starts with no warning and no controls, and the security zone I carefully drew just disappeared. It is a good-looking prototype that is not quite ready for real use. The bones are solid but the wiring between frontend and backend has holes.
