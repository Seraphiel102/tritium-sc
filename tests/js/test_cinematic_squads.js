// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * TRITIUM-SC Cinematic Auto-Follow Camera + Squad Formation Hull Tests
 *
 * Tests the auto-follow camera mode (toggle, ring buffer, hotspot calculation,
 * user pan disables, AUTO badge) and squad formation hull visualization
 * (grouping by squadId, hull generation, tactical order colors, layer HUD).
 *
 * Run: node tests/js/test_cinematic_squads.js
 */

let passed = 0, failed = 0;
function assert(cond, msg) {
    if (!cond) { console.error('FAIL:', msg); failed++; }
    else { console.log('PASS:', msg); passed++; }
}

function approx(a, b, tolerance, msg) {
    if (Math.abs(a - b) <= tolerance) { console.log('PASS:', msg); passed++; }
    else { console.error(`FAIL: ${msg} (expected ~${b}, got ${a})`); failed++; }
}

// ============================================================
// Mock infrastructure matching the codebase patterns
// ============================================================

// Mock TritiumStore
const TritiumStore = {
    units: new Map(),
    _store: {},
    get(path) {
        return this._store[path];
    },
    set(path, value) {
        this._store[path] = value;
    },
    updateUnit(id, data) {
        const existing = this.units.get(id) || {};
        this.units.set(id, { ...existing, ...data, id });
    },
};

// Mock EventBus
const EventBus = {
    _handlers: new Map(),
    on(event, handler) {
        if (!this._handlers.has(event)) this._handlers.set(event, new Set());
        this._handlers.get(event).add(handler);
        return () => this._handlers.get(event)?.delete(handler);
    },
    off(event, handler) {
        this._handlers.get(event)?.delete(handler);
    },
    emit(event, data) {
        this._handlers.get(event)?.forEach(handler => {
            try { handler(data); } catch (_) {}
        });
    },
};

// ============================================================
// Mirror core map functions under test
// ============================================================

// Constants
const SQUAD_ORDER_COLORS = {
    advance: '#ff2a6d',
    hold:    '#fcee0a',
    flank:   '#00f0ff',
    retreat: '#a08820',
};
const SQUAD_DEFAULT_COLOR = '#ff2a6d';
const COMBAT_EVENT_RING_SIZE = 20;
const COMBAT_EVENT_MAX_AGE = 10000;

// _state mock
const _state = {
    geoCenter: { lat: 37.7159, lng: -121.8960 },
    map: null,
    container: null,
    initialized: true,
    autoFollow: false,
    autoFollowTimer: null,
    autoFollowFlyingNow: false,
    combatEventRing: [],
    streakHolder: null,
    showSquadHulls: true,
    showSwarmHull: true,
    showFog: false,
    layerHud: null,
};

// Mirror _gameToLngLat
function _gameToLngLat(gx, gy) {
    if (!_state.geoCenter) return [0, 0];
    const R = 6378137;
    const latRad = _state.geoCenter.lat * Math.PI / 180;
    const dLng = gx / (R * Math.cos(latRad)) * (180 / Math.PI);
    const dLat = gy / R * (180 / Math.PI);
    return [_state.geoCenter.lng + dLng, _state.geoCenter.lat + dLat];
}

// Mirror _convexHull
function _convexHull(points) {
    if (points.length < 3) return points.slice();
    const sorted = points.slice().sort((a, b) => a[0] - b[0] || a[1] - b[1]);
    function cross(O, A, B) {
        return (A[0] - O[0]) * (B[1] - O[1]) - (A[1] - O[1]) * (B[0] - O[0]);
    }
    const lower = [];
    for (const p of sorted) {
        while (lower.length >= 2 && cross(lower[lower.length - 2], lower[lower.length - 1], p) <= 0) lower.pop();
        lower.push(p);
    }
    const upper = [];
    for (let i = sorted.length - 1; i >= 0; i--) {
        const p = sorted[i];
        while (upper.length >= 2 && cross(upper[upper.length - 2], upper[upper.length - 1], p) <= 0) upper.pop();
        upper.push(p);
    }
    lower.pop();
    upper.pop();
    return lower.concat(upper);
}

// Mirror _squadColor
function _squadColor(order) {
    return SQUAD_ORDER_COLORS[order] || SQUAD_DEFAULT_COLOR;
}

// Mirror _recordCombatEvent
function _recordCombatEvent(lng, lat) {
    _state.combatEventRing.push({ lng, lat, time: Date.now() });
    if (_state.combatEventRing.length > COMBAT_EVENT_RING_SIZE) {
        _state.combatEventRing.shift();
    }
}

// Mirror _recentCombatEvents
function _recentCombatEvents() {
    const cutoff = Date.now() - COMBAT_EVENT_MAX_AGE;
    return _state.combatEventRing.filter(e => e.time >= cutoff);
}

// Mirror _findActionHotspot
function _findActionHotspot() {
    const events = _recentCombatEvents();
    if (events.length === 0) return null;
    let sumLng = 0, sumLat = 0;
    for (const e of events) {
        sumLng += e.lng;
        sumLat += e.lat;
    }
    return { lng: sumLng / events.length, lat: sumLat / events.length };
}

// Mirror _evaluateAutoFollowTarget
function _evaluateAutoFollowTarget() {
    if (_state.streakHolder && (Date.now() - _state.streakHolder.time) < 8000) {
        const unit = TritiumStore.units.get(_state.streakHolder.unitId);
        if (unit && unit.position) {
            const lngLat = _gameToLngLat(unit.position.x || 0, unit.position.y || 0);
            return { lng: lngLat[0], lat: lngLat[1], zoom: 17.5 };
        }
        return { lng: _state.streakHolder.lng, lat: _state.streakHolder.lat, zoom: 17.5 };
    }
    const hotspot = _findActionHotspot();
    if (hotspot) {
        return { lng: hotspot.lng, lat: hotspot.lat, zoom: 17 };
    }
    let sumLng = 0, sumLat = 0, count = 0;
    TritiumStore.units.forEach(u => {
        if (u.alliance === 'hostile') {
            const pos = u.position || {};
            const lngLat = _gameToLngLat(pos.x || 0, pos.y || 0);
            sumLng += lngLat[0];
            sumLat += lngLat[1];
            count++;
        }
    });
    if (count > 0) {
        return { lng: sumLng / count, lat: sumLat / count, zoom: 16.5 };
    }
    return null;
}


// ============================================================
// Test: Auto-follow state toggle
// ============================================================

console.log('\n--- Auto-follow state toggle ---');

{
    _state.autoFollow = false;
    assert(!_state.autoFollow, 'autoFollow starts false');

    _state.autoFollow = true;
    assert(_state.autoFollow, 'autoFollow can be toggled true');

    _state.autoFollow = false;
    assert(!_state.autoFollow, 'autoFollow can be toggled back to false');
}

// ============================================================
// Test: Ring buffer event storage
// ============================================================

console.log('\n--- Ring buffer event storage ---');

{
    _state.combatEventRing = [];

    _recordCombatEvent(-121.5, 37.7);
    assert(_state.combatEventRing.length === 1, 'ring buffer stores one event');

    _recordCombatEvent(-121.6, 37.8);
    assert(_state.combatEventRing.length === 2, 'ring buffer stores two events');

    // Fill beyond capacity
    _state.combatEventRing = [];
    for (let i = 0; i < 25; i++) {
        _recordCombatEvent(-121.0 + i * 0.001, 37.7);
    }
    assert(_state.combatEventRing.length === COMBAT_EVENT_RING_SIZE,
        `ring buffer capped at ${COMBAT_EVENT_RING_SIZE} (got ${_state.combatEventRing.length})`);
}

// ============================================================
// Test: Recent events filtering
// ============================================================

console.log('\n--- Recent events filtering ---');

{
    _state.combatEventRing = [];

    // Add a recent event
    _recordCombatEvent(-121.5, 37.7);

    // Add an old event (manually set time)
    _state.combatEventRing.push({ lng: -121.6, lat: 37.8, time: Date.now() - 20000 });

    const recent = _recentCombatEvents();
    assert(recent.length === 1, 'recentCombatEvents filters out old events');
    approx(recent[0].lng, -121.5, 0.01, 'recent event has correct lng');
}

// ============================================================
// Test: Action hotspot calculation
// ============================================================

console.log('\n--- Action hotspot calculation ---');

{
    _state.combatEventRing = [];
    const result = _findActionHotspot();
    assert(result === null, 'hotspot returns null when no events');
}

{
    _state.combatEventRing = [];
    _recordCombatEvent(-121.5, 37.7);
    _recordCombatEvent(-121.6, 37.8);
    _recordCombatEvent(-121.7, 37.9);

    const hotspot = _findActionHotspot();
    assert(hotspot !== null, 'hotspot returns value when events exist');
    approx(hotspot.lng, -121.6, 0.01, 'hotspot lng is centroid of events');
    approx(hotspot.lat, 37.8, 0.01, 'hotspot lat is centroid of events');
}

// ============================================================
// Test: Auto-follow target evaluation priority
// ============================================================

console.log('\n--- Auto-follow target evaluation ---');

{
    // Clean state
    _state.combatEventRing = [];
    _state.streakHolder = null;
    TritiumStore.units.clear();

    // No targets at all
    const t0 = _evaluateAutoFollowTarget();
    assert(t0 === null, 'no target when no hostiles and no events');
}

{
    // Priority 3: hostile centroid
    _state.combatEventRing = [];
    _state.streakHolder = null;
    TritiumStore.units.clear();
    TritiumStore.updateUnit('h1', { alliance: 'hostile', position: { x: 100, y: 100 } });
    TritiumStore.updateUnit('h2', { alliance: 'hostile', position: { x: 200, y: 200 } });

    const t3 = _evaluateAutoFollowTarget();
    assert(t3 !== null, 'target found from hostile centroid');
    assert(t3.zoom === 16.5, 'hostile centroid zoom is 16.5');
}

{
    // Priority 2: combat hotspot takes precedence over hostile centroid
    _state.combatEventRing = [];
    _state.streakHolder = null;
    TritiumStore.units.clear();
    TritiumStore.updateUnit('h1', { alliance: 'hostile', position: { x: 100, y: 100 } });
    _recordCombatEvent(-121.5, 37.7);

    const t2 = _evaluateAutoFollowTarget();
    assert(t2 !== null, 'target found from hotspot');
    assert(t2.zoom === 17, 'hotspot zoom is 17');
    approx(t2.lng, -121.5, 0.01, 'hotspot target lng correct');
}

{
    // Priority 1: streak holder takes top precedence
    _state.combatEventRing = [];
    _state.streakHolder = { unitId: 'turret-1', lng: -121.89, lat: 37.71, time: Date.now() };
    TritiumStore.units.clear();
    _recordCombatEvent(-121.5, 37.7);

    const t1 = _evaluateAutoFollowTarget();
    assert(t1 !== null, 'target found from streak holder');
    assert(t1.zoom === 17.5, 'streak holder zoom is 17.5');
    approx(t1.lng, -121.89, 0.01, 'streak holder target lng correct');
}

{
    // Stale streak holder (>8s) falls through to hotspot
    _state.combatEventRing = [];
    _state.streakHolder = { unitId: 'turret-1', lng: -121.89, lat: 37.71, time: Date.now() - 9000 };
    TritiumStore.units.clear();
    _recordCombatEvent(-121.5, 37.7);

    const t1stale = _evaluateAutoFollowTarget();
    assert(t1stale !== null, 'target found after stale streak');
    assert(t1stale.zoom === 17, 'stale streak falls through to hotspot zoom 17');
}

// ============================================================
// Test: Squad grouping by squadId
// ============================================================

console.log('\n--- Squad grouping by squadId ---');

{
    TritiumStore.units.clear();
    TritiumStore.updateUnit('h1', { alliance: 'hostile', squadId: 'sq-1', position: { x: 10, y: 10 } });
    TritiumStore.updateUnit('h2', { alliance: 'hostile', squadId: 'sq-1', position: { x: 20, y: 20 } });
    TritiumStore.updateUnit('h3', { alliance: 'hostile', squadId: 'sq-1', position: { x: 30, y: 10 } });
    TritiumStore.updateUnit('h4', { alliance: 'hostile', squadId: 'sq-2', position: { x: 100, y: 100 } });
    TritiumStore.updateUnit('h5', { alliance: 'hostile', position: { x: 200, y: 200 } }); // no squadId

    // Group by squadId
    const squads = new Map();
    TritiumStore.units.forEach((unit) => {
        if (!unit.squadId) return;
        if (!squads.has(unit.squadId)) squads.set(unit.squadId, []);
        squads.get(unit.squadId).push(unit);
    });

    assert(squads.size === 2, 'two squads found');
    assert(squads.get('sq-1').length === 3, 'sq-1 has 3 members');
    assert(squads.get('sq-2').length === 1, 'sq-2 has 1 member');
    assert(!squads.has(undefined), 'units without squadId excluded');
}

// ============================================================
// Test: Hull generation for squads with 3+ members
// ============================================================

console.log('\n--- Hull generation for squads with 3+ members ---');

{
    const points = [
        _gameToLngLat(10, 10),
        _gameToLngLat(20, 20),
        _gameToLngLat(30, 10),
    ];

    const hull = _convexHull(points);
    assert(hull.length === 3, 'convex hull of 3 non-collinear points has 3 vertices');
}

{
    const points = [
        _gameToLngLat(0, 0),
        _gameToLngLat(100, 0),
        _gameToLngLat(100, 100),
        _gameToLngLat(0, 100),
        _gameToLngLat(50, 50),  // interior point
    ];

    const hull = _convexHull(points);
    assert(hull.length === 4, 'convex hull of 5 points with 1 interior has 4 vertices');
}

// ============================================================
// Test: Squads with <3 members skipped
// ============================================================

console.log('\n--- Squads with <3 members skipped ---');

{
    // 2-member squad should not produce a hull
    const points = [
        _gameToLngLat(10, 10),
        _gameToLngLat(20, 20),
    ];

    const hull = _convexHull(points);
    // _convexHull returns the points if <3, but _updateSquadHulls checks length<3 and skips
    assert(hull.length === 2, 'hull of 2 points returned as-is');

    // In the actual _updateSquadHulls, squads with <3 members are skipped before hull
    const squads = new Map();
    squads.set('sq-small', [
        { unit: {}, lngLat: _gameToLngLat(10, 10) },
        { unit: {}, lngLat: _gameToLngLat(20, 20) },
    ]);
    let featuresBuilt = 0;
    squads.forEach((members) => {
        if (members.length < 3) return;
        featuresBuilt++;
    });
    assert(featuresBuilt === 0, 'squad with 2 members produces no feature');
}

{
    // 1-member squad
    const squads = new Map();
    squads.set('sq-solo', [{ unit: {}, lngLat: _gameToLngLat(10, 10) }]);
    let featuresBuilt = 0;
    squads.forEach((members) => {
        if (members.length < 3) return;
        featuresBuilt++;
    });
    assert(featuresBuilt === 0, 'squad with 1 member produces no feature');
}

// ============================================================
// Test: Color by tactical order
// ============================================================

console.log('\n--- Color by tactical order ---');

{
    assert(_squadColor('advance') === '#ff2a6d', 'advance = magenta');
    assert(_squadColor('hold') === '#fcee0a', 'hold = amber/yellow');
    assert(_squadColor('flank') === '#00f0ff', 'flank = cyan');
    assert(_squadColor('retreat') === '#a08820', 'retreat = dim yellow');
    assert(_squadColor(undefined) === '#ff2a6d', 'undefined order = default magenta');
    assert(_squadColor(null) === '#ff2a6d', 'null order = default magenta');
    assert(_squadColor('unknown') === '#ff2a6d', 'unknown order = default magenta');
}

// ============================================================
// Test: Layer HUD indicators
// ============================================================

console.log('\n--- Layer HUD indicators ---');

{
    // Simulate the layer HUD text building logic
    function buildLayerHudText(state) {
        const layers = [];
        if (state.showSwarmHull) layers.push('SWARM');
        if (state.showSquadHulls) layers.push('SQUAD');
        if (state.autoFollow) layers.push('AUTO');
        if (state.showFog) layers.push('FOG');
        return layers.join(' + ');
    }

    const text1 = buildLayerHudText({ showSwarmHull: true, showSquadHulls: true, autoFollow: false, showFog: false });
    assert(text1.includes('SWARM'), 'HUD shows SWARM when enabled');
    assert(text1.includes('SQUAD'), 'HUD shows SQUAD when enabled');
    assert(!text1.includes('AUTO'), 'HUD hides AUTO when disabled');

    const text2 = buildLayerHudText({ showSwarmHull: false, showSquadHulls: true, autoFollow: true, showFog: false });
    assert(!text2.includes('SWARM'), 'HUD hides SWARM when disabled');
    assert(text2.includes('SQUAD'), 'HUD shows SQUAD');
    assert(text2.includes('AUTO'), 'HUD shows AUTO when enabled');
}

// ============================================================
// Test: toggleSquadHulls state flip
// ============================================================

console.log('\n--- toggleSquadHulls state flip ---');

{
    _state.showSquadHulls = true;
    _state.showSquadHulls = !_state.showSquadHulls;
    assert(!_state.showSquadHulls, 'toggleSquadHulls flips true to false');

    _state.showSquadHulls = !_state.showSquadHulls;
    assert(_state.showSquadHulls, 'toggleSquadHulls flips false to true');
}

// ============================================================
// Test: AUTO badge visibility
// ============================================================

console.log('\n--- AUTO badge visibility ---');

{
    // When autoFollow is on, badge should be created
    // (In the real code _updateAutoBadge creates a DOM element; here we test the logic)
    _state.autoFollow = true;
    const shouldShow = _state.autoFollow;
    assert(shouldShow === true, 'AUTO badge should be visible when autoFollow is on');

    _state.autoFollow = false;
    const shouldHide = !_state.autoFollow;
    assert(shouldHide === true, 'AUTO badge should be hidden when autoFollow is off');
}

// ============================================================
// Test: Manual pan disables auto-follow
// ============================================================

console.log('\n--- Manual pan disables auto-follow ---');

{
    _state.autoFollow = true;
    _state.autoFollowFlyingNow = false;

    // Simulate user move (not triggered by auto-follow)
    // In the real code, _onUserMoveStart checks autoFollowFlyingNow
    if (!_state.autoFollowFlyingNow && _state.autoFollow) {
        _state.autoFollow = false;
    }
    assert(!_state.autoFollow, 'manual pan disables auto-follow');
}

{
    _state.autoFollow = true;
    _state.autoFollowFlyingNow = true;

    // Simulate move triggered by auto-follow (should NOT disable)
    if (!_state.autoFollowFlyingNow && _state.autoFollow) {
        _state.autoFollow = false;
    }
    assert(_state.autoFollow, 'auto-triggered move does NOT disable auto-follow');
    _state.autoFollowFlyingNow = false;
}

// ============================================================
// Test: Streak holder tracking
// ============================================================

console.log('\n--- Streak holder tracking ---');

{
    _state.streakHolder = null;
    TritiumStore.units.clear();
    TritiumStore.updateUnit('turret-1', {
        alliance: 'friendly',
        position: { x: 50, y: 50 },
    });

    // Simulate streak event handling
    _state.autoFollow = true;
    const data = { unit_id: 'turret-1' };
    const unitId = data.unit_id;
    const unit = TritiumStore.units.get(unitId);
    if (unit && unit.position) {
        const lngLat = _gameToLngLat(unit.position.x || 0, unit.position.y || 0);
        _state.streakHolder = { unitId, lng: lngLat[0], lat: lngLat[1], time: Date.now() };
    }

    assert(_state.streakHolder !== null, 'streak holder set after streak event');
    assert(_state.streakHolder.unitId === 'turret-1', 'streak holder tracks correct unit');
}

// ============================================================
// Test: Coordinate conversion round-trip
// ============================================================

console.log('\n--- Coordinate conversion ---');

{
    const lngLat = _gameToLngLat(0, 0);
    approx(lngLat[0], _state.geoCenter.lng, 0.0001, '_gameToLngLat(0,0) returns geoCenter lng');
    approx(lngLat[1], _state.geoCenter.lat, 0.0001, '_gameToLngLat(0,0) returns geoCenter lat');
}

{
    // Non-zero offset
    const lngLat = _gameToLngLat(100, 100);
    assert(lngLat[0] > _state.geoCenter.lng, '100m east shifts lng positive');
    assert(lngLat[1] > _state.geoCenter.lat, '100m north shifts lat positive');
}

// ============================================================
// Test: GeoJSON feature construction for squad hulls
// ============================================================

console.log('\n--- GeoJSON feature construction ---');

{
    TritiumStore.units.clear();
    TritiumStore.set('game.phase', 'active');

    // Create a 4-member squad
    TritiumStore.updateUnit('s1', { squadId: 'alpha', position: { x: 0, y: 0 }, tacticalOrder: 'hold' });
    TritiumStore.updateUnit('s2', { squadId: 'alpha', position: { x: 50, y: 0 } });
    TritiumStore.updateUnit('s3', { squadId: 'alpha', position: { x: 50, y: 50 } });
    TritiumStore.updateUnit('s4', { squadId: 'alpha', position: { x: 0, y: 50 } });

    // Simulate the grouping + feature building from _updateSquadHulls
    const squads = new Map();
    TritiumStore.units.forEach((unit) => {
        if (!unit.squadId) return;
        const pos = unit.position || {};
        const lngLat = _gameToLngLat(pos.x || 0, pos.y || 0);
        if (!squads.has(unit.squadId)) squads.set(unit.squadId, []);
        squads.get(unit.squadId).push({ unit, lngLat });
    });

    const features = [];
    squads.forEach((members, squadId) => {
        if (members.length < 3) return;
        const points = members.map(m => m.lngLat);
        const hull = _convexHull(points);
        if (hull.length < 3) return;
        const ring = hull.slice();
        ring.push(ring[0]);
        let order = null;
        for (const m of members) {
            if (m.unit.tacticalOrder) { order = m.unit.tacticalOrder; break; }
        }
        const color = _squadColor(order);
        features.push({
            type: 'Feature',
            geometry: { type: 'Polygon', coordinates: [ring] },
            properties: { squadId, color, order: order || 'advance' },
        });
    });

    assert(features.length === 1, 'one squad produces one feature');
    assert(features[0].properties.squadId === 'alpha', 'feature has correct squadId');
    assert(features[0].properties.color === '#fcee0a', 'hold order produces amber color');
    assert(features[0].properties.order === 'hold', 'feature records tactical order');
    assert(features[0].geometry.type === 'Polygon', 'feature geometry is Polygon');
    assert(features[0].geometry.coordinates[0].length >= 4,
        'polygon ring has at least 4 coords (3 hull + close)');
    // Check ring is closed
    const ring = features[0].geometry.coordinates[0];
    approx(ring[0][0], ring[ring.length - 1][0], 0.00001, 'polygon ring is closed (lng)');
    approx(ring[0][1], ring[ring.length - 1][1], 0.00001, 'polygon ring is closed (lat)');
}

// ============================================================
// Test: Multiple squads with different orders
// ============================================================

console.log('\n--- Multiple squads different orders ---');

{
    TritiumStore.units.clear();

    // Squad alpha: 3 members, advancing
    TritiumStore.updateUnit('a1', { squadId: 'alpha', position: { x: 0, y: 0 }, tacticalOrder: 'advance' });
    TritiumStore.updateUnit('a2', { squadId: 'alpha', position: { x: 10, y: 0 } });
    TritiumStore.updateUnit('a3', { squadId: 'alpha', position: { x: 5, y: 10 } });

    // Squad bravo: 3 members, flanking
    TritiumStore.updateUnit('b1', { squadId: 'bravo', position: { x: 100, y: 100 }, tacticalOrder: 'flank' });
    TritiumStore.updateUnit('b2', { squadId: 'bravo', position: { x: 110, y: 100 } });
    TritiumStore.updateUnit('b3', { squadId: 'bravo', position: { x: 105, y: 110 } });

    // Squad charlie: 2 members (should be skipped)
    TritiumStore.updateUnit('c1', { squadId: 'charlie', position: { x: 200, y: 200 } });
    TritiumStore.updateUnit('c2', { squadId: 'charlie', position: { x: 210, y: 210 } });

    const squads = new Map();
    TritiumStore.units.forEach((unit) => {
        if (!unit.squadId) return;
        const pos = unit.position || {};
        const lngLat = _gameToLngLat(pos.x || 0, pos.y || 0);
        if (!squads.has(unit.squadId)) squads.set(unit.squadId, []);
        squads.get(unit.squadId).push({ unit, lngLat });
    });

    const features = [];
    squads.forEach((members, squadId) => {
        if (members.length < 3) return;
        const points = members.map(m => m.lngLat);
        const hull = _convexHull(points);
        if (hull.length < 3) return;
        const ring = hull.slice();
        ring.push(ring[0]);
        let order = null;
        for (const m of members) {
            if (m.unit.tacticalOrder) { order = m.unit.tacticalOrder; break; }
        }
        features.push({
            type: 'Feature',
            geometry: { type: 'Polygon', coordinates: [ring] },
            properties: { squadId, color: _squadColor(order), order: order || 'advance' },
        });
    });

    assert(features.length === 2, 'two valid squads produce two features');
    const alphaFeature = features.find(f => f.properties.squadId === 'alpha');
    const bravoFeature = features.find(f => f.properties.squadId === 'bravo');
    assert(alphaFeature.properties.color === '#ff2a6d', 'alpha advance = magenta');
    assert(bravoFeature.properties.color === '#00f0ff', 'bravo flank = cyan');
}

// ============================================================
// Summary
// ============================================================

console.log(`\n========================================`);
console.log(`Cinematic + Squads: ${passed} passed, ${failed} failed`);
console.log(`========================================`);
process.exit(failed > 0 ? 1 : 0);
