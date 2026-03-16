# Layer System Status

## Overview

The tactical map supports 50+ toggleable layers organized in 8 categories. Layers can be controlled via:
- **MAP menu** → Show All / Hide All / individual toggles
- **Layers panel** (press L) → per-layer + per-category + global controls
- **Keyboard shortcuts** — I, K, G, H, U, F for common layers

## Categories

### BASE MAP (7 layers)
| Layer | Key | Status | Notes |
|-------|-----|--------|-------|
| Satellite Imagery | showSatellite | Working | Esri World Imagery tiles |
| Building Outlines | showBuildings | Working | Cyan outlines from OpenFreeMap |
| Road Network | showRoads | Working | OpenFreeMap vector tiles |
| Waterways | showWaterways | Working | Streams and channels |
| Parks & Green Spaces | showParks | Working | Parks, fields |
| Coordinate Grid | showGrid | Working | Tactical reference grid |
| 3D Terrain | showTerrain | Working | Mapzen DEM elevation mesh |

### MESH NETWORK (4 layers)
| Layer | Key | Status | Notes |
|-------|-----|--------|-------|
| Meshtastic Network | showMesh | Working | Master toggle |
| Mesh Nodes | showMeshNodes | Working | Green radio icons |
| Mesh Links | showMeshLinks | Working | SNR-colored connection lines |
| Mesh Coverage | showMeshCoverage | Working | ~10km radius circles |

### UNITS & FORCES (7 layers)
| Layer | Key | Status | Notes |
|-------|-----|--------|-------|
| Unit Markers | showUnits | Working | NATO-style alliance-colored markers |
| 3D Unit Models | showModels3d | Working | Three.js models when zoomed in |
| Unit Labels | showLabels | Working | Callsign text |
| Health Bars | showHealthBars | Working | HP bars + damage glow |
| Selection Effects | showSelectionFx | Working | Glow highlight on selected unit |
| Weapon Range | showWeaponRange | Working | Range circle on selected unit |
| Thought Bubbles | showThoughts | Working | LLM-generated thoughts |

### TACTICAL OVERLAYS (17 layers)
| Layer | Key | Status | Notes |
|-------|-----|--------|-------|
| Patrol Routes | showPatrolRoutes | Working | Green dashed waypoint paths |
| Squad Formations | showSquadHulls | Working | Convex hull outlines |
| Drone Swarm Hull | showSwarmHull | Working | Swarm convex hull |
| Hostile Objectives | showHostileObjectives | Working | Dashed lines to targets |
| Hostile Intel HUD | showHostileIntel | Working | Enemy commander display |
| Cover Points | showCoverPoints | Working | Directional cover positions |
| Hazard Zones | showHazardZones | Working | Fires, roadblocks |
| Unit Signals | showUnitSignals | Working | Distress/contact/rally signals |
| Fog of War | showFog | Working | Vision-based darkness |
| Combat Heatmap | showHeatmap | Working | Combat density overlay |
| Crowd Density | showCrowdDensity | Working | Civilian crowd heatmap |
| Activity Heatmap | showActivityHeatmap | Working | Multi-source activity density |
| Coverage Overlap | showCoverageOverlap | Working | Multi-sensor redundancy |
| Correlation Lines | showCorrelationLines | Working | Cross-sensor entity links |
| Prediction Cones | showPredictionCones | Working | Future position estimates |
| Threat Direction | showDirectionalThreatArrows | Working | Threat approach arrows |
| Geofence Zones | showGeofenceZones | Working | Monitored/restricted areas |
| Sensor Coverage | showCoverage | Working | BLE/WiFi node ranges |
| Movement Trails | trails:toggle | Working | Speed-colored target trails |

### COMBAT EFFECTS (8 layers)
| Layer | Key | Status | Notes |
|-------|-----|--------|-------|
| Projectile Tracers | showTracers | Working | Glowing tracer lines |
| Explosions | showExplosions | Working | Explosion effects |
| Debris & Sparks | showParticles | Working | Particle effects |
| Hit Flashes | showHitFlashes | Working | Impact flash |
| Damage Numbers | showFloatingText | Working | Floating damage text |
| Kill Feed | showKillFeed | Working | Combat log |
| Screen Effects | showScreenFx | Working | Screen shake/flash |
| Banners | showBanners | Working | Wave start/end banners |

### GIS INTELLIGENCE (dynamic)
Loaded from `/api/geo/layers/catalog`. Includes power lines, traffic signals, water towers, etc.

### GIS DATA SOURCES (dynamic)
Loaded from `/api/gis/layers`. Managed tile/vector sources.

### INTERFACE (2 layers)
| Layer | Key | Status | Notes |
|-------|-----|--------|-------|
| Status HUD | showLayerHud | Working | Active layer bar |
| Auto-Follow Camera | autoFollow | Working | Follow combat action |

## Known Issues

1. **MAP menu "Hide All" vs Layers panel "HIDE ALL"** — now both use `setAllLayers(false)` for consistent behavior
2. **Some map state keys are UI state, not layers** — showGameOverOverlay, showGeofencePrompt, etc. are not in the Layers panel intentionally (they're modal UI, not map layers)
3. **GIS layers** have their own toggle system separate from the main map state — the Layers panel handles both

## Controls

| Action | MAP Menu | Layers Panel | Keyboard |
|--------|----------|-------------|----------|
| Open layers | MAP → Open Layers Window | — | L |
| Show all layers | MAP → Show All Layers | SHOW ALL button | — |
| Hide all layers | MAP → Hide All Layers | HIDE ALL button | — |
| Toggle category | — | ALL / NONE per category | — |
| Toggle individual | MAP → checkboxes | per-layer checkbox | I, K, G, H, U, F |
