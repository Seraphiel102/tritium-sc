// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * TRITIUM-SC ADS-B Aircraft Overlay tests
 *
 * Validates the ADS-B overlay module:
 * 1. Module exports: start, stop, toggle, isActive
 * 2. Altitude color interpolation
 * 3. Flight level formatting
 * 4. Marker creation and update logic
 * 5. Trail management
 * 6. Emergency squawk handling
 * 7. Stale marker cleanup
 * 8. Integration with menu-bar, main.js, and CSS
 *
 * Run: node tests/js/test_adsb_overlay.js
 */

const fs = require('fs');

// Simple test runner
let passed = 0, failed = 0;
function assert(cond, msg) {
    if (!cond) { console.error('FAIL:', msg); failed++; }
    else { console.log('PASS:', msg); passed++; }
}

// Read source files
const overlaySrc = fs.readFileSync(
    __dirname + '/../../src/frontend/js/command/adsb-overlay.js', 'utf8'
);
const mainSrc = fs.readFileSync(
    __dirname + '/../../src/frontend/js/command/main.js', 'utf8'
);
const menuBarSrc = fs.readFileSync(
    __dirname + '/../../src/frontend/js/command/menu-bar.js', 'utf8'
);
const cssSrc = fs.readFileSync(
    __dirname + '/../../src/frontend/css/command.css', 'utf8'
);

// Also read the table panel
const tableSrc = fs.readFileSync(
    __dirname + '/../../src/frontend/js/command/panels/adsb-table.js', 'utf8'
);


// ============================================================
// 1. Module Exports
// ============================================================

console.log('\n--- ADS-B Overlay: module exports ---');

assert(
    /export\s+function\s+startAdsbOverlay\b/.test(overlaySrc),
    'startAdsbOverlay() is exported'
);
assert(
    /export\s+function\s+stopAdsbOverlay\b/.test(overlaySrc),
    'stopAdsbOverlay() is exported'
);
assert(
    /export\s+function\s+toggleAdsbOverlay\b/.test(overlaySrc),
    'toggleAdsbOverlay() is exported'
);
assert(
    /export\s+function\s+isAdsbOverlayActive\b/.test(overlaySrc),
    'isAdsbOverlayActive() is exported'
);


// ============================================================
// 2. Constants
// ============================================================

console.log('\n--- ADS-B Overlay: constants ---');

assert(
    overlaySrc.includes('FETCH_INTERVAL_MS'),
    'FETCH_INTERVAL_MS constant defined'
);
assert(
    /FETCH_INTERVAL_MS\s*=\s*2000/.test(overlaySrc),
    'FETCH_INTERVAL_MS = 2000 (2 second polling)'
);
assert(
    overlaySrc.includes('TRAIL_MAX_POINTS'),
    'TRAIL_MAX_POINTS constant defined'
);
assert(
    /TRAIL_MAX_POINTS\s*=\s*20/.test(overlaySrc),
    'TRAIL_MAX_POINTS = 20'
);
assert(
    overlaySrc.includes('ALT_COLORS'),
    'ALT_COLORS altitude color stops defined'
);
assert(
    overlaySrc.includes('EMERGENCY_COLOR'),
    'EMERGENCY_COLOR defined'
);
assert(
    overlaySrc.includes('AIRPLANE_SVG'),
    'AIRPLANE_SVG icon defined'
);


// ============================================================
// 3. Cyberpunk Color Scheme
// ============================================================

console.log('\n--- ADS-B Overlay: cyberpunk color scheme ---');

assert(
    overlaySrc.includes('#05ffa1'),
    'Green (#05ffa1) used for low altitude'
);
assert(
    overlaySrc.includes('#00f0ff'),
    'Cyan (#00f0ff) used for mid altitude'
);
assert(
    overlaySrc.includes('#ff2a6d'),
    'Magenta (#ff2a6d) used for high altitude'
);


// ============================================================
// 4. Altitude Color Function
// ============================================================

console.log('\n--- ADS-B Overlay: altitude color function ---');

assert(
    overlaySrc.includes('function _altitudeColor'),
    '_altitudeColor() function exists'
);
assert(
    overlaySrc.includes('function _lerpColor'),
    '_lerpColor() helper function exists'
);

// Verify altitude stops include ground, low, mid, high
assert(
    /alt:\s*0/.test(overlaySrc),
    'Altitude color has ground stop (0 ft)'
);
assert(
    /alt:\s*5000/.test(overlaySrc),
    'Altitude color has low stop (5000 ft)'
);
assert(
    /alt:\s*15000/.test(overlaySrc),
    'Altitude color has mid stop (15000 ft)'
);
assert(
    /alt:\s*30000/.test(overlaySrc),
    'Altitude color has high stop (30000 ft)'
);
assert(
    /alt:\s*45000/.test(overlaySrc),
    'Altitude color has very high stop (45000 ft)'
);


// ============================================================
// 5. Flight Level Formatting
// ============================================================

console.log('\n--- ADS-B Overlay: flight level formatting ---');

assert(
    overlaySrc.includes('function _flightLevel'),
    '_flightLevel() function exists'
);
// Should output FL for >= 1000 ft, raw feet for < 1000
assert(
    /FL.*Math\.round\(altFt\s*\/\s*100\)/.test(overlaySrc),
    '_flightLevel computes FL from altitude/100'
);
assert(
    /altFt\s*<\s*1000/.test(overlaySrc),
    '_flightLevel uses raw feet for altitudes below 1000'
);


// ============================================================
// 6. Marker Creation
// ============================================================

console.log('\n--- ADS-B Overlay: marker creation ---');

assert(
    overlaySrc.includes('function _createMarkerEl'),
    '_createMarkerEl() function exists'
);
assert(
    overlaySrc.includes('adsb-aircraft-marker'),
    'Marker uses adsb-aircraft-marker CSS class'
);
assert(
    overlaySrc.includes('adsb-icon'),
    'Icon container uses adsb-icon CSS class'
);
assert(
    overlaySrc.includes('adsb-label'),
    'Label uses adsb-label CSS class'
);
assert(
    /rotate\(.*(track\.heading|heading)/.test(overlaySrc),
    'Icon is rotated by heading'
);
assert(
    /transition.*transform.*ease/.test(overlaySrc),
    'Rotation has smooth CSS transition'
);


// ============================================================
// 7. Marker Update
// ============================================================

console.log('\n--- ADS-B Overlay: marker update ---');

assert(
    overlaySrc.includes('function _updateMarkerEl'),
    '_updateMarkerEl() function exists'
);
assert(
    /rotate\(.*heading/.test(overlaySrc),
    'Update function rotates icon to new heading'
);


// ============================================================
// 8. Trail Management
// ============================================================

console.log('\n--- ADS-B Overlay: trail management ---');

assert(
    overlaySrc.includes('function _updateTrail'),
    '_updateTrail() function exists'
);
assert(
    overlaySrc.includes('function _renderTrails'),
    '_renderTrails() function exists'
);
assert(
    overlaySrc.includes('function _removeTrail'),
    '_removeTrail() function exists'
);
assert(
    overlaySrc.includes('TRAIL_MAX_POINTS'),
    'Trail length is bounded by TRAIL_MAX_POINTS'
);
assert(
    /trail\.shift\(\)/.test(overlaySrc),
    'Old trail points are shifted out when max reached'
);
assert(
    /LineString/.test(overlaySrc),
    'Trail rendered as GeoJSON LineString'
);
assert(
    /adsb-trail-/.test(overlaySrc),
    'Trail sources/layers use adsb-trail- prefix'
);
assert(
    /line-dasharray/.test(overlaySrc),
    'Trail lines use dash pattern'
);


// ============================================================
// 9. Emergency Squawk Handling
// ============================================================

console.log('\n--- ADS-B Overlay: emergency squawk ---');

assert(
    overlaySrc.includes('is_emergency'),
    'Checks is_emergency flag on track data'
);
assert(
    overlaySrc.includes('adsb-emergency'),
    'Emergency markers get adsb-emergency CSS class'
);
assert(
    /EMERGENCY_COLOR.*#ff0000/.test(overlaySrc),
    'Emergency color is red (#ff0000)'
);


// ============================================================
// 10. Data Fetching
// ============================================================

console.log('\n--- ADS-B Overlay: data fetching ---');

assert(
    overlaySrc.includes('function _fetchAndRender'),
    '_fetchAndRender() function exists'
);
assert(
    overlaySrc.includes("'/api/sdr/adsb'"),
    'Fetches from /api/sdr/adsb endpoint'
);
assert(
    overlaySrc.includes('data.tracks'),
    'Parses tracks array from API response'
);
assert(
    overlaySrc.includes('window._mapState'),
    'References window._mapState for map instance'
);


// ============================================================
// 11. Stale Marker Cleanup
// ============================================================

console.log('\n--- ADS-B Overlay: stale marker cleanup ---');

assert(
    overlaySrc.includes('seenIcao'),
    'Tracks seen ICAO codes for stale detection'
);
assert(
    /marker\.remove\(\)/.test(overlaySrc),
    'Stale markers are removed from map'
);
assert(
    /delete\s+_markers\[/.test(overlaySrc),
    'Stale marker entries are deleted from state'
);


// ============================================================
// 12. EventBus Integration
// ============================================================

console.log('\n--- ADS-B Overlay: EventBus integration ---');

assert(
    overlaySrc.includes("import { EventBus }"),
    'Imports EventBus'
);
assert(
    overlaySrc.includes("EventBus.emit('adsb:select'"),
    'Emits adsb:select on marker click'
);
assert(
    overlaySrc.includes("EventBus.emit('adsb:count'"),
    'Emits adsb:count with track count'
);


// ============================================================
// 13. Stop/Cleanup
// ============================================================

console.log('\n--- ADS-B Overlay: stop/cleanup ---');

assert(
    /clearInterval\(_pollTimer\)/.test(overlaySrc),
    'stopAdsbOverlay clears poll timer'
);
assert(
    /_markers\s*=\s*\{\}/.test(overlaySrc),
    'stopAdsbOverlay resets markers state'
);
assert(
    /_trails\s*=\s*\{\}/.test(overlaySrc),
    'stopAdsbOverlay resets trails state'
);


// ============================================================
// 14. SVG Icon
// ============================================================

console.log('\n--- ADS-B Overlay: SVG airplane icon ---');

assert(
    overlaySrc.includes('<svg'),
    'AIRPLANE_SVG contains SVG markup'
);
assert(
    /viewBox.*0\s+0\s+24\s+24/.test(overlaySrc),
    'SVG uses 24x24 viewBox'
);
assert(
    overlaySrc.includes('currentColor'),
    'SVG fill uses currentColor for dynamic coloring'
);


// ============================================================
// 15. Integration: main.js imports and wiring
// ============================================================

console.log('\n--- Integration: main.js ---');

assert(
    mainSrc.includes("from './adsb-overlay.js'"),
    'main.js imports from adsb-overlay.js'
);
assert(
    mainSrc.includes('startAdsbOverlay'),
    'main.js imports startAdsbOverlay'
);
assert(
    mainSrc.includes('startAdsbOverlay()'),
    'main.js calls startAdsbOverlay() at init'
);


// ============================================================
// 16. Integration: menu-bar.js toggle
// ============================================================

console.log('\n--- Integration: menu-bar.js ---');

assert(
    menuBarSrc.includes("from './adsb-overlay.js'"),
    'menu-bar.js imports from adsb-overlay.js'
);
assert(
    menuBarSrc.includes('toggleAdsbOverlay'),
    'menu-bar.js imports toggleAdsbOverlay'
);
assert(
    menuBarSrc.includes('isAdsbOverlayActive'),
    'menu-bar.js imports isAdsbOverlayActive'
);
assert(
    menuBarSrc.includes("'ADS-B Aircraft'"),
    'ADS-B Aircraft appears in View menu'
);
assert(
    /checkable:\s*true.*isAdsbOverlayActive/.test(menuBarSrc),
    'ADS-B menu item is checkable using isAdsbOverlayActive'
);


// ============================================================
// 17. Integration: CSS styles
// ============================================================

console.log('\n--- Integration: CSS ---');

assert(
    cssSrc.includes('.adsb-aircraft-marker'),
    '.adsb-aircraft-marker CSS rule exists'
);
assert(
    cssSrc.includes('.adsb-emergency'),
    '.adsb-emergency CSS class exists'
);
assert(
    cssSrc.includes('adsb-emergency-pulse'),
    'adsb-emergency-pulse keyframe animation defined'
);


// ============================================================
// 18. ADS-B Table Panel
// ============================================================

console.log('\n--- ADS-B Table Panel ---');

assert(
    /export\s+(const|let|var)\s+AdsbTablePanelDef\b/.test(tableSrc),
    'AdsbTablePanelDef is exported'
);
assert(
    tableSrc.includes("id: 'adsb-table'"),
    'Panel ID is adsb-table'
);
assert(
    tableSrc.includes("'ADS-B AIRCRAFT'") || tableSrc.includes("\"ADS-B AIRCRAFT\""),
    'Panel title is ADS-B AIRCRAFT'
);
assert(
    tableSrc.includes("'/api/sdr/adsb'"),
    'Table panel fetches from /api/sdr/adsb'
);
assert(
    mainSrc.includes('AdsbTablePanelDef'),
    'main.js imports AdsbTablePanelDef'
);
assert(
    mainSrc.includes("register(AdsbTablePanelDef)"),
    'main.js registers AdsbTablePanelDef with panelManager'
);
assert(
    menuBarSrc.includes("'adsb-table'"),
    'adsb-table is listed in menu-bar panel categories'
);


// ============================================================
// 19. Table Panel: Columns
// ============================================================

console.log('\n--- ADS-B Table: columns ---');

const expectedCols = ['callsign', 'icao_hex', 'altitude_ft', 'speed_kts', 'heading', 'lat', 'lng', 'squawk', 'vertical_rate'];
for (const col of expectedCols) {
    assert(
        tableSrc.includes(`key: '${col}'`),
        `Table has column: ${col}`
    );
}


// ============================================================
// 20. Table Panel: Emergency Squawk Detection
// ============================================================

console.log('\n--- ADS-B Table: squawk alerts ---');

assert(
    tableSrc.includes("'7500'"),
    'Table detects squawk 7500 (hijack)'
);
assert(
    tableSrc.includes("'7600'"),
    'Table detects squawk 7600 (radio failure)'
);
assert(
    tableSrc.includes("'7700'"),
    'Table detects squawk 7700 (emergency)'
);
assert(
    tableSrc.includes('HIJACK'),
    'Squawk 7500 labeled HIJACK'
);
assert(
    tableSrc.includes('EMERGENCY'),
    'Squawk 7700 labeled EMERGENCY'
);


// ============================================================
// 21. Table Panel: Sorting
// ============================================================

console.log('\n--- ADS-B Table: sorting ---');

assert(
    tableSrc.includes('function sortTracks'),
    'sortTracks() function exists'
);
assert(
    /sortKey.*altitude_ft/.test(tableSrc),
    'Default sort is by altitude'
);
assert(
    tableSrc.includes('localeCompare'),
    'String columns use localeCompare for sorting'
);


// ============================================================
// 22. Table Panel: Map Integration
// ============================================================

console.log('\n--- ADS-B Table: map interaction ---');

assert(
    tableSrc.includes("EventBus.emit('map:flyTo'"),
    'Row click emits map:flyTo to center map on aircraft'
);
assert(
    tableSrc.includes("EventBus.on('adsb:tracks_updated'"),
    'Table listens for adsb:tracks_updated WebSocket events'
);


// ============================================================
// 23. Graceful no-data handling
// ============================================================

console.log('\n--- ADS-B: graceful degradation ---');

assert(
    overlaySrc.includes('if (!resp.ok) return'),
    'Overlay handles non-OK HTTP responses gracefully'
);
assert(
    /catch\s*\(_\)/.test(overlaySrc),
    'Overlay catches fetch errors silently'
);
assert(
    tableSrc.includes('NO ADS-B RECEIVER CONNECTED'),
    'Table shows empty state message when no data'
);
assert(
    tableSrc.includes('/api/sdr/demo/start'),
    'Table suggests demo mode when no receiver'
);


// ============================================================
// Summary
// ============================================================

console.log('\n========================================');
console.log(`ADS-B Overlay Tests: ${passed} passed, ${failed} failed`);
console.log('========================================');
process.exit(failed > 0 ? 1 : 0);
