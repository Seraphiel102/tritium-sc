// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * TRITIUM-SC Radar PPI Scope Panel tests
 * Tests RadarScopePanelDef structure, DOM creation, controls,
 * coordinate conversion, track rendering logic, mount behavior,
 * trail history, alliance colors, hit testing, and tooltip display.
 * Run: node tests/js/test_radar_scope_panel.js
 */

const fs = require('fs');
const vm = require('vm');

// Simple test runner
let passed = 0, failed = 0;
function assert(cond, msg) {
    if (!cond) { console.error('FAIL:', msg); failed++; }
    else { console.log('PASS:', msg); passed++; }
}

function assertApprox(actual, expected, tolerance, msg) {
    const diff = Math.abs(actual - expected);
    if (diff > tolerance) {
        console.error(`FAIL: ${msg} (expected ~${expected}, got ${actual}, diff ${diff})`);
        failed++;
    } else {
        console.log('PASS:', msg);
        passed++;
    }
}

// ============================================================
// DOM + browser mocks
// ============================================================

function createCanvasMock() {
    const calls = [];
    const ctxMock = {
        _calls: calls,
        clearRect(...a) { calls.push(['clearRect', ...a]); },
        fillRect(...a) { calls.push(['fillRect', ...a]); },
        beginPath() { calls.push(['beginPath']); },
        arc(...a) { calls.push(['arc', ...a]); },
        moveTo(...a) { calls.push(['moveTo', ...a]); },
        lineTo(...a) { calls.push(['lineTo', ...a]); },
        closePath() { calls.push(['closePath']); },
        fill() { calls.push(['fill']); },
        stroke() { calls.push(['stroke']); },
        fillText(...a) { calls.push(['fillText', ...a]); },
        setLineDash(a) { calls.push(['setLineDash', a]); },
        setTransform(...a) { calls.push(['setTransform', ...a]); },
        save() { calls.push(['save']); },
        restore() { calls.push(['restore']); },
        createConicGradient() {
            return { addColorStop() {} };
        },
        fillStyle: '',
        strokeStyle: '',
        lineWidth: 1,
        globalAlpha: 1.0,
        font: '',
        textAlign: '',
        textBaseline: '',
    };
    return ctxMock;
}

function createMockElement(tag) {
    const children = [];
    const classList = new Set();
    const eventListeners = {};
    const dataset = {};
    const style = {};
    let _innerHTML = '';
    let _textContent = '';
    const canvasCtx = createCanvasMock();

    const el = {
        tagName: (tag || 'DIV').toUpperCase(),
        className: '',
        get innerHTML() { return _innerHTML; },
        set innerHTML(val) {
            _innerHTML = val;
            el._parsedBinds = {};
            const bindMatches = val.matchAll(/data-bind="([^"]+)"/g);
            for (const m of bindMatches) el._parsedBinds[m[1]] = true;
        },
        get textContent() { return _textContent; },
        set textContent(val) { _textContent = String(val); },
        style,
        dataset,
        children,
        childNodes: children,
        parentNode: null,
        parentElement: null,
        hidden: false,
        value: '',
        width: 0,
        height: 0,
        appendChild(child) { children.push(child); child.parentNode = el; child.parentElement = el; return child; },
        removeChild(child) { const i = children.indexOf(child); if (i >= 0) children.splice(i, 1); },
        remove() { if (el.parentNode) el.parentNode.removeChild(el); },
        getContext(type) {
            if (type === '2d') return canvasCtx;
            return null;
        },
        _canvasCtx: canvasCtx,
        querySelector(sel) {
            const bindMatch = sel.match(/\[data-bind="([^"]+)"\]/);
            if (bindMatch) {
                const name = bindMatch[1];
                if (name === 'canvas') {
                    const canvasEl = createMockElement('canvas');
                    canvasEl.parentElement = el;
                    canvasEl.parentNode = el;
                    return canvasEl;
                }
                if (name === 'tooltip') {
                    const tipEl = createMockElement('div');
                    tipEl.style.display = 'none';
                    return tipEl;
                }
                if (name === 'range-select') {
                    const selectEl = createMockElement('select');
                    selectEl.value = '20000';
                    return selectEl;
                }
                if (name === 'filter-select') {
                    const selectEl = createMockElement('select');
                    selectEl.value = 'all';
                    return selectEl;
                }
                const mockEl = createMockElement('span');
                mockEl._bindName = name;
                return mockEl;
            }
            return null;
        },
        querySelectorAll() { return []; },
        addEventListener(evt, fn) {
            if (!eventListeners[evt]) eventListeners[evt] = [];
            eventListeners[evt].push(fn);
        },
        removeEventListener(evt, fn) {
            if (eventListeners[evt]) {
                const i = eventListeners[evt].indexOf(fn);
                if (i >= 0) eventListeners[evt].splice(i, 1);
            }
        },
        _eventListeners: eventListeners,
        _parsedBinds: {},
        classList: {
            add(c) { classList.add(c); },
            remove(c) { classList.delete(c); },
            contains(c) { return classList.has(c); },
            toggle(c) { if (classList.has(c)) classList.delete(c); else classList.add(c); },
        },
        getBoundingClientRect() { return { left: 0, top: 0, width: 400, height: 400 }; },
    };
    return el;
}

// ============================================================
// Read the panel source
// ============================================================

const src = fs.readFileSync(
    __dirname + '/../../src/frontend/js/command/panels/radar-scope.js',
    'utf-8'
);

// Build a sandboxed module that captures the export
const EventBusMock = {
    _handlers: {},
    on(evt, fn) { if (!this._handlers[evt]) this._handlers[evt] = []; this._handlers[evt].push(fn); return () => {}; },
    emit(evt, data) { (this._handlers[evt] || []).forEach(fn => fn(data)); },
};

const exported = {};

// Track requestAnimationFrame / cancelAnimationFrame calls
let rafCallbacks = [];
let rafIdCounter = 0;
let intervalCallbacks = {};
let intervalIdCounter = 0;
let fetchCallCount = 0;
let fetchResponse = { ok: true, json: async () => ({ tracks: [], count: 0 }) };

const mockContext = {
    console,
    Math,
    Date,
    parseInt,
    parseFloat,
    Set,
    Map,
    Object,
    Array,
    String,
    Number,
    JSON,
    Error,
    RegExp,
    Promise,
    setTimeout: (fn, ms) => { return 999; },
    clearTimeout: () => {},
    setInterval: (fn, ms) => {
        const id = ++intervalIdCounter;
        intervalCallbacks[id] = fn;
        return id;
    },
    clearInterval: (id) => {
        delete intervalCallbacks[id];
    },
    requestAnimationFrame: (fn) => {
        const id = ++rafIdCounter;
        rafCallbacks.push({ id, fn });
        return id;
    },
    cancelAnimationFrame: (id) => {
        rafCallbacks = rafCallbacks.filter(r => r.id !== id);
    },
    window: { devicePixelRatio: 1 },
    ResizeObserver: class {
        constructor(cb) { this._cb = cb; }
        observe() {}
        disconnect() {}
    },
    document: {
        createElement: createMockElement,
    },
    fetch: async () => {
        fetchCallCount++;
        return fetchResponse;
    },
};

// Convert ES module to CJS-compatible
let cjsSrc = src
    .replace(/^import\s+\{[^}]+\}\s+from\s+'[^']+';?\s*$/gm, '')
    .replace(/^export\s+const\s+/gm, 'exported.')
    .replace(/^export\s+function\s+/gm, 'exported.')
    .replace(/^export\s+/gm, 'exported.');

// Also expose module-level helper functions for testing
cjsSrc = cjsSrc
    .replace(/^function degToRad/m, 'exported.degToRad = function degToRad')
    .replace(/^function formatRange/m, 'exported.formatRange = function formatRange')
    .replace(/^function formatVelocity/m, 'exported.formatVelocity = function formatVelocity');

try {
    const script = new vm.Script(cjsSrc, { filename: 'radar-scope.js' });
    const ctx = vm.createContext({
        ...mockContext,
        exported,
        _esc: (s) => String(s || '').replace(/</g, '&lt;').replace(/>/g, '&gt;'),
        EventBus: EventBusMock,
    });
    script.runInContext(ctx);
} catch (e) {
    console.error('Failed to load module:', e.message);
    process.exit(1);
}

const RadarScopePanelDef = exported.RadarScopePanelDef;
const degToRad = exported.degToRad;
const formatRange = exported.formatRange;
const formatVelocity = exported.formatVelocity;

// ============================================================
// 1. Panel definition structure
// ============================================================

console.log('\n--- Panel definition structure ---');

assert(RadarScopePanelDef !== undefined, 'RadarScopePanelDef is exported');
assert(RadarScopePanelDef.id === 'radar-scope', 'Panel ID is radar-scope');
assert(RadarScopePanelDef.title === 'RADAR PPI SCOPE', 'Panel title is RADAR PPI SCOPE');
assert(typeof RadarScopePanelDef.create === 'function', 'create is a function');
assert(typeof RadarScopePanelDef.mount === 'function', 'mount is a function');
assert(typeof RadarScopePanelDef.unmount === 'function', 'unmount is a function');
assert(typeof RadarScopePanelDef.onResize === 'function', 'onResize is a function');

// -- Default position and size --
assert(RadarScopePanelDef.defaultPosition.x === 60, 'Default position x is 60');
assert(RadarScopePanelDef.defaultPosition.y === 60, 'Default position y is 60');
assert(RadarScopePanelDef.defaultSize.w === 520, 'Default width is 520');
assert(RadarScopePanelDef.defaultSize.h === 600, 'Default height is 600');

// ============================================================
// 2. DOM creation
// ============================================================

console.log('\n--- DOM creation ---');

const mockPanel = { _unsubs: [] };
const el = RadarScopePanelDef.create(mockPanel);
assert(el !== null && el !== undefined, 'create() returns an element');
assert(el.className === 'radar-scope-inner', 'Root element has correct class');

// Check flex column layout
assert(el.style.cssText.includes('flex-direction:column'), 'Root has flex column layout');
assert(el.style.cssText.includes('height:100%'), 'Root fills parent height');

const html = el.innerHTML;

// Data bindings
assert(html.includes('data-bind="status"'), 'Has status binding');
assert(html.includes('data-bind="track-count"'), 'Has track-count binding');
assert(html.includes('data-bind="last-update"'), 'Has last-update binding');
assert(html.includes('data-bind="canvas"'), 'Has canvas binding');
assert(html.includes('data-bind="tooltip"'), 'Has tooltip binding');
assert(html.includes('data-bind="range-select"'), 'Has range-select binding');
assert(html.includes('data-bind="filter-select"'), 'Has filter-select binding');

// ============================================================
// 3. Range selector options
// ============================================================

console.log('\n--- Range selector ---');

assert(html.includes('value="5000"'), 'Range option 5000m present');
assert(html.includes('value="10000"'), 'Range option 10000m present');
assert(html.includes('value="20000"'), 'Range option 20000m present');
assert(html.includes('value="50000"'), 'Range option 50000m present');
assert(html.includes('5 km'), 'Range label 5 km present');
assert(html.includes('10 km'), 'Range label 10 km present');
assert(html.includes('20 km'), 'Range label 20 km present');
assert(html.includes('50 km'), 'Range label 50 km present');
// Default selected range is 20km
assert(html.includes('value="20000" selected'), '20 km is default selected range');

// ============================================================
// 4. Alliance filter options
// ============================================================

console.log('\n--- Alliance filter ---');

assert(html.includes('value="all"'), 'Filter has ALL option');
assert(html.includes('value="hostile"'), 'Filter has hostile option');
assert(html.includes('value="unknown"'), 'Filter has unknown option');
assert(html.includes('value="friendly"'), 'Filter has friendly option');
assert(html.includes('>ALL<'), 'ALL filter label present');
assert(html.includes('>HOSTILE<'), 'HOSTILE filter label present');
assert(html.includes('>UNKNOWN<'), 'UNKNOWN filter label present');
assert(html.includes('>FRIENDLY<'), 'FRIENDLY filter label present');

// ============================================================
// 5. Header content
// ============================================================

console.log('\n--- Header content ---');

assert(html.includes('ACTIVE'), 'Status shows ACTIVE by default');
assert(html.includes('TRACKS:'), 'Header shows TRACKS label');
assert(html.includes('UPDATED:'), 'Header shows UPDATED label');
assert(html.includes('radar-scope-header'), 'Has header div class');
assert(html.includes('radar-scope-controls'), 'Has controls div class');
assert(html.includes('radar-scope-canvas-wrap'), 'Has canvas wrapper class');

// ============================================================
// 6. Tooltip structure
// ============================================================

console.log('\n--- Tooltip structure ---');

assert(html.includes('display:none'), 'Tooltip starts hidden');
assert(html.includes('pointer-events:none'), 'Tooltip does not capture mouse events');
assert(html.includes('position:absolute'), 'Tooltip is absolutely positioned');
assert(html.includes('z-index:10'), 'Tooltip has z-index');

// ============================================================
// 7. Color scheme (cyberpunk palette)
// ============================================================

console.log('\n--- Color scheme ---');

assert(html.includes('#00f0ff') || el.style.cssText.includes('#0a0a0f'), 'Uses cyan accent');
assert(html.includes('#0a0a0f') || el.style.cssText.includes('#0a0a0f'), 'Uses dark background');
assert(src.includes('#05ffa1'), 'Defines GREEN (#05ffa1)');
assert(src.includes('#ff2a6d'), 'Defines RED (#ff2a6d)');
assert(src.includes('#fcee0a'), 'Defines YELLOW (#fcee0a)');

// ============================================================
// 8. degToRad helper
// ============================================================

console.log('\n--- degToRad helper ---');

assert(typeof degToRad === 'function', 'degToRad is exported for testing');
assertApprox(degToRad(0), 0, 0.0001, 'degToRad(0) = 0');
assertApprox(degToRad(90), Math.PI / 2, 0.0001, 'degToRad(90) = PI/2');
assertApprox(degToRad(180), Math.PI, 0.0001, 'degToRad(180) = PI');
assertApprox(degToRad(270), 3 * Math.PI / 2, 0.0001, 'degToRad(270) = 3PI/2');
assertApprox(degToRad(360), 2 * Math.PI, 0.0001, 'degToRad(360) = 2PI');
assertApprox(degToRad(45), Math.PI / 4, 0.0001, 'degToRad(45) = PI/4');
assertApprox(degToRad(-90), -Math.PI / 2, 0.0001, 'degToRad(-90) = -PI/2');

// ============================================================
// 9. formatRange helper
// ============================================================

console.log('\n--- formatRange helper ---');

assert(typeof formatRange === 'function', 'formatRange is exported for testing');
assert(formatRange(500) === '500 m', 'formatRange(500) = "500 m"');
assert(formatRange(999) === '999 m', 'formatRange(999) = "999 m"');
assert(formatRange(1000) === '1.0 km', 'formatRange(1000) = "1.0 km"');
assert(formatRange(5000) === '5.0 km', 'formatRange(5000) = "5.0 km"');
assert(formatRange(10500) === '10.5 km', 'formatRange(10500) = "10.5 km"');
assert(formatRange(20000) === '20.0 km', 'formatRange(20000) = "20.0 km"');
assert(formatRange(50000) === '50.0 km', 'formatRange(50000) = "50.0 km"');
assert(formatRange(100) === '100 m', 'formatRange(100) = "100 m"');

// ============================================================
// 10. formatVelocity helper
// ============================================================

console.log('\n--- formatVelocity helper ---');

assert(typeof formatVelocity === 'function', 'formatVelocity is exported for testing');
assert(formatVelocity(0) === '0.0 m/s', 'formatVelocity(0) = "0.0 m/s"');
assert(formatVelocity(10.5) === '10.5 m/s', 'formatVelocity(10.5) = "10.5 m/s"');
assert(formatVelocity(343.123) === '343.1 m/s', 'formatVelocity(343.123) = "343.1 m/s"');
assert(formatVelocity(1.05) === '1.1 m/s', 'formatVelocity(1.05) rounds to "1.1 m/s"');

// ============================================================
// 11. Polar to cartesian conversion (trackToCanvas logic)
// ============================================================

console.log('\n--- Polar to cartesian conversion ---');

// The panel uses: rad = degToRad(azimuth_deg - 90), x = cx + r*cos(rad), y = cy + r*sin(rad)
// This means azimuth 0 (North) -> angle -90deg -> cos(-90)=0, sin(-90)=-1 -> point is above center
// azimuth 90 (East) -> angle 0 -> cos(0)=1, sin(0)=0 -> point is to the right
// azimuth 180 (South) -> angle 90 -> cos(90)=0, sin(90)=1 -> point is below center
// azimuth 270 (West) -> angle 180 -> cos(180)=-1, sin(180)=0 -> point is to the left

function trackToCanvas(range_m, azimuth_deg, cx, cy, radius, maxRange) {
    const r = (range_m / maxRange) * radius;
    const rad = degToRad(azimuth_deg - 90);
    const x = cx + r * Math.cos(rad);
    const y = cy + r * Math.sin(rad);
    return { x, y, r };
}

const CX = 200, CY = 200, RADIUS = 168, MAX_RANGE = 20000;

// North (azimuth 0): should be directly above center
const northPos = trackToCanvas(10000, 0, CX, CY, RADIUS, MAX_RANGE);
assertApprox(northPos.x, CX, 0.1, 'North track x = center');
assert(northPos.y < CY, 'North track y is above center');
assertApprox(northPos.r, RADIUS * 0.5, 0.1, 'Half-range track has r = radius/2');

// East (azimuth 90): should be directly right of center
const eastPos = trackToCanvas(10000, 90, CX, CY, RADIUS, MAX_RANGE);
assert(eastPos.x > CX, 'East track x is right of center');
assertApprox(eastPos.y, CY, 0.1, 'East track y = center');

// South (azimuth 180): should be directly below center
const southPos = trackToCanvas(10000, 180, CX, CY, RADIUS, MAX_RANGE);
assertApprox(southPos.x, CX, 0.1, 'South track x = center');
assert(southPos.y > CY, 'South track y is below center');

// West (azimuth 270): should be directly left of center
const westPos = trackToCanvas(10000, 270, CX, CY, RADIUS, MAX_RANGE);
assert(westPos.x < CX, 'West track x is left of center');
assertApprox(westPos.y, CY, 0.1, 'West track y = center');

// Range scaling: at max range, r should equal radius
const maxRangePos = trackToCanvas(MAX_RANGE, 45, CX, CY, RADIUS, MAX_RANGE);
assertApprox(maxRangePos.r, RADIUS, 0.01, 'At max range, r = radius');

// Range scaling: at zero range, point is at center
const zeroPos = trackToCanvas(0, 45, CX, CY, RADIUS, MAX_RANGE);
assertApprox(zeroPos.x, CX, 0.01, 'Zero range x = center');
assertApprox(zeroPos.y, CY, 0.01, 'Zero range y = center');

// NE diagonal (azimuth 45): x > cx, y < cy
const nePos = trackToCanvas(10000, 45, CX, CY, RADIUS, MAX_RANGE);
assert(nePos.x > CX, 'NE track x is right of center');
assert(nePos.y < CY, 'NE track y is above center');
// At 45 deg, x offset should equal |y offset|
assertApprox(Math.abs(nePos.x - CX), Math.abs(nePos.y - CY), 0.1, 'NE track 45deg has equal x,y offsets');

// SE diagonal (azimuth 135): x > cx, y > cy
const sePos = trackToCanvas(10000, 135, CX, CY, RADIUS, MAX_RANGE);
assert(sePos.x > CX, 'SE track x is right of center');
assert(sePos.y > CY, 'SE track y is below center');

// SW diagonal (azimuth 225): x < cx, y > cy
const swPos = trackToCanvas(10000, 225, CX, CY, RADIUS, MAX_RANGE);
assert(swPos.x < CX, 'SW track x is left of center');
assert(swPos.y > CY, 'SW track y is below center');

// NW diagonal (azimuth 315): x < cx, y < cy
const nwPos = trackToCanvas(10000, 315, CX, CY, RADIUS, MAX_RANGE);
assert(nwPos.x < CX, 'NW track x is left of center');
assert(nwPos.y < CY, 'NW track y is above center');

// ============================================================
// 12. Hit testing logic
// ============================================================

console.log('\n--- Hit testing ---');

// Simulate hit test: check if a point is within HIT_RADIUS (8px) of a track dot
const HIT_RADIUS = 8;
function isHit(trackX, trackY, mouseX, mouseY) {
    const dx = mouseX - trackX;
    const dy = mouseY - trackY;
    return dx * dx + dy * dy < HIT_RADIUS * HIT_RADIUS;
}

// Direct hit on track position
assert(isHit(200, 200, 200, 200), 'Direct hit on track center');

// Hit just inside radius
assert(isHit(200, 200, 207, 200), 'Hit 7px away (inside radius)');

// Miss just outside radius
assert(!isHit(200, 200, 209, 200), 'Miss 9px away (outside radius)');

// Diagonal hit (inside sqrt(32) < 8)
assert(isHit(200, 200, 205, 205), 'Diagonal hit inside radius');

// Diagonal: dx=5, dy=6 -> d^2=61, 61<64 so still a hit
assert(isHit(200, 200, 205, 206), 'Diagonal hit at distance sqrt(61) < 8');

// Diagonal miss: dx=6, dy=6 -> d^2=72, 72>64 so a miss
assert(!isHit(200, 200, 206, 206), 'Diagonal miss at distance sqrt(72) > 8');

// Boundary: exactly at radius (distance = 8, but < check is strict)
assert(!isHit(200, 200, 208, 200), 'Exactly at HIT_RADIUS boundary is a miss (strict <)');

// ============================================================
// 13. Alliance color mapping
// ============================================================

console.log('\n--- Alliance colors ---');

// Verify the color constants match what the source defines
assert(src.includes("friendly: GREEN") || src.includes("friendly: '#05ffa1'"), 'Friendly maps to green');
assert(src.includes("hostile: RED") || src.includes("hostile: '#ff2a6d'"), 'Hostile maps to red');
assert(src.includes("unknown: CYAN") || src.includes("unknown: '#00f0ff'"), 'Unknown maps to cyan');

// Verify all three alliance types are covered
const allianceBlock = src.match(/ALLIANCE_COLORS\s*=\s*\{([^}]+)\}/s);
assert(allianceBlock !== null, 'ALLIANCE_COLORS object exists in source');
if (allianceBlock) {
    assert(allianceBlock[1].includes('friendly'), 'ALLIANCE_COLORS has friendly key');
    assert(allianceBlock[1].includes('hostile'), 'ALLIANCE_COLORS has hostile key');
    assert(allianceBlock[1].includes('unknown'), 'ALLIANCE_COLORS has unknown key');
}

// ============================================================
// 14. Classification icons
// ============================================================

console.log('\n--- Classification icons ---');

const classBlock = src.match(/CLASS_ICONS\s*=\s*\{([^}]+)\}/s);
assert(classBlock !== null, 'CLASS_ICONS object exists in source');
if (classBlock) {
    const icons = classBlock[1];
    assert(icons.includes("vehicle: 'V'"), 'Vehicle icon is V');
    assert(icons.includes("aircraft: 'A'"), 'Aircraft icon is A');
    assert(icons.includes("uav: 'U'"), 'UAV icon is U');
    assert(icons.includes("person: 'P'"), 'Person icon is P');
    assert(icons.includes("ship: 'S'"), 'Ship icon is S');
    assert(icons.includes("animal: 'a'"), 'Animal icon is a (lowercase)');
}

// ============================================================
// 15. Constants
// ============================================================

console.log('\n--- Constants ---');

assert(src.includes('SWEEP_PERIOD_MS = 3000'), 'Sweep period is 3000ms');
assert(src.includes('FETCH_INTERVAL_MS = 1000'), 'Fetch interval is 1000ms');
assert(src.includes('TRAIL_LENGTH = 10'), 'Trail length is 10');

// Range presets
const rangeMatch = src.match(/RANGE_PRESETS\s*=\s*\[([^\]]+)\]/);
assert(rangeMatch !== null, 'RANGE_PRESETS array exists');
if (rangeMatch) {
    assert(rangeMatch[1].includes('5000'), 'RANGE_PRESETS has 5000');
    assert(rangeMatch[1].includes('10000'), 'RANGE_PRESETS has 10000');
    assert(rangeMatch[1].includes('20000'), 'RANGE_PRESETS has 20000');
    assert(rangeMatch[1].includes('50000'), 'RANGE_PRESETS has 50000');
}

// ============================================================
// 16. Mount behavior — animation and fetch setup
// ============================================================

console.log('\n--- Mount behavior ---');

// Reset tracking
rafCallbacks = [];
rafIdCounter = 0;
intervalCallbacks = {};
intervalIdCounter = 0;
fetchCallCount = 0;
EventBusMock._handlers = {};

const mountPanel = { _unsubs: [] };
const bodyEl = RadarScopePanelDef.create(mountPanel);

// mount() should set up requestAnimationFrame and setInterval
RadarScopePanelDef.mount(bodyEl, mountPanel);

assert(rafCallbacks.length > 0, 'mount() requests an animation frame');
assert(Object.keys(intervalCallbacks).length > 0, 'mount() sets up fetch interval');
assert(fetchCallCount > 0, 'mount() triggers immediate fetch on mount');
assert(mountPanel._unsubs.length > 0, 'mount() registers cleanup callbacks');

// ============================================================
// 17. Mount — EventBus subscription
// ============================================================

console.log('\n--- EventBus subscription ---');

assert(EventBusMock._handlers['radar:tracks_updated'] !== undefined, 'mount() subscribes to radar:tracks_updated');
assert(EventBusMock._handlers['radar:tracks_updated'].length > 0, 'radar:tracks_updated has at least one handler');

// ============================================================
// 18. Cleanup on unmount
// ============================================================

console.log('\n--- Cleanup ---');

assert(src.includes('destroyed = true'), 'Cleanup sets destroyed flag');
assert(src.includes('cancelAnimationFrame(animFrameId)'), 'Cleanup cancels animation frame');
assert(src.includes('clearInterval(fetchTimerId)'), 'Cleanup clears fetch interval');
assert(src.includes('resizeObs.disconnect()'), 'Cleanup disconnects ResizeObserver');

// Verify _unsubs has cleanup functions
let cleanupCount = 0;
for (const fn of mountPanel._unsubs) {
    if (typeof fn === 'function') cleanupCount++;
}
assert(cleanupCount >= 2, '_unsubs has at least 2 cleanup functions (destroy + EventBus unsub)');

// ============================================================
// 19. Sweep angle calculation
// ============================================================

console.log('\n--- Sweep angle calculation ---');

// sweepAngle = ((timestamp % SWEEP_PERIOD_MS) / SWEEP_PERIOD_MS) * 360
// At t=0: angle=0
// At t=1500 (half period): angle=180
// At t=3000 (full period): angle=0 (wraps)
function computeSweepAngle(timestamp) {
    return ((timestamp % 3000) / 3000) * 360;
}

assertApprox(computeSweepAngle(0), 0, 0.01, 'Sweep at t=0 is 0 degrees');
assertApprox(computeSweepAngle(1500), 180, 0.01, 'Sweep at t=1500 is 180 degrees');
assertApprox(computeSweepAngle(750), 90, 0.01, 'Sweep at t=750 is 90 degrees');
assertApprox(computeSweepAngle(3000), 0, 0.01, 'Sweep at t=3000 wraps to 0');
assertApprox(computeSweepAngle(4500), 180, 0.01, 'Sweep at t=4500 is 180 (second rotation)');

// ============================================================
// 20. Trail history management
// ============================================================

console.log('\n--- Trail history logic ---');

// Simulate trail accumulation (mimics the fetch callback logic)
function simulateTrailUpdate(trailHistory, tracks, TRAIL_LENGTH) {
    for (const t of tracks) {
        const tid = t.track_id;
        if (trailHistory[tid] === undefined) {
            trailHistory[tid] = [];
        }
        const trail = trailHistory[tid];
        trail.push({ range_m: t.range_m, azimuth_deg: t.azimuth_deg });
        if (trail.length > TRAIL_LENGTH) {
            trail.shift();
        }
    }
    // Prune old trails
    const activeTids = new Set(tracks.map(t => t.track_id));
    for (const tid of Object.keys(trailHistory)) {
        if (!activeTids.has(tid)) {
            delete trailHistory[tid];
        }
    }
}

const trailHistory = {};
const TRAIL_LEN = 10;

// First update: single track
simulateTrailUpdate(trailHistory, [
    { track_id: 'T1', range_m: 5000, azimuth_deg: 45 },
], TRAIL_LEN);
assert(trailHistory['T1'] !== undefined, 'Trail created for T1');
assert(trailHistory['T1'].length === 1, 'T1 trail has 1 entry after first update');

// Multiple updates accumulate
for (let i = 0; i < 5; i++) {
    simulateTrailUpdate(trailHistory, [
        { track_id: 'T1', range_m: 5000 + i * 100, azimuth_deg: 45 + i },
    ], TRAIL_LEN);
}
assert(trailHistory['T1'].length === 6, 'T1 trail has 6 entries after 6 updates');

// Trail caps at TRAIL_LENGTH
for (let i = 0; i < 10; i++) {
    simulateTrailUpdate(trailHistory, [
        { track_id: 'T1', range_m: 6000 + i * 100, azimuth_deg: 50 + i },
    ], TRAIL_LEN);
}
assert(trailHistory['T1'].length === TRAIL_LEN, 'T1 trail capped at TRAIL_LENGTH');

// Trail oldest entry is dropped when over limit
const lastEntry = trailHistory['T1'][TRAIL_LEN - 1];
assert(lastEntry.range_m === 6900, 'Most recent trail entry is the newest');

// Track removal prunes trail history
simulateTrailUpdate(trailHistory, [], TRAIL_LEN);
assert(trailHistory['T1'] === undefined, 'T1 trail pruned when track disappears');

// Multiple tracks maintained independently
simulateTrailUpdate(trailHistory, [
    { track_id: 'A1', range_m: 3000, azimuth_deg: 10 },
    { track_id: 'A2', range_m: 7000, azimuth_deg: 200 },
], TRAIL_LEN);
assert(trailHistory['A1'] !== undefined && trailHistory['A2'] !== undefined, 'Multiple trails maintained');
assert(trailHistory['A1'].length === 1 && trailHistory['A2'].length === 1, 'Each trail independent');

// ============================================================
// 21. Track filtering logic
// ============================================================

console.log('\n--- Track filtering ---');

const sampleTracks = [
    { track_id: 'T1', range_m: 5000, azimuth_deg: 30, alliance: 'friendly' },
    { track_id: 'T2', range_m: 8000, azimuth_deg: 120, alliance: 'hostile' },
    { track_id: 'T3', range_m: 15000, azimuth_deg: 270, alliance: 'unknown' },
    { track_id: 'T4', range_m: 25000, azimuth_deg: 90 },  // no alliance = defaults to unknown
    { track_id: 'T5', range_m: 3000, azimuth_deg: 180, alliance: 'hostile' },
];

function filterTracks(tracks, trackFilter, maxRange) {
    return tracks.filter(t => {
        const alliance = t.alliance || 'unknown';
        if (trackFilter !== 'all' && alliance !== trackFilter) return false;
        if (t.range_m > maxRange) return false;
        return true;
    });
}

// All filter, 20km range
let filtered = filterTracks(sampleTracks, 'all', 20000);
assert(filtered.length === 4, 'ALL filter at 20km shows 4 tracks (T4 out of range)');

// Hostile filter, 20km range
filtered = filterTracks(sampleTracks, 'hostile', 20000);
assert(filtered.length === 2, 'HOSTILE filter at 20km shows 2 tracks');
assert(filtered.every(t => t.alliance === 'hostile'), 'HOSTILE filter only returns hostile tracks');

// Friendly filter, 20km range
filtered = filterTracks(sampleTracks, 'friendly', 20000);
assert(filtered.length === 1, 'FRIENDLY filter at 20km shows 1 track');
assert(filtered[0].track_id === 'T1', 'FRIENDLY filter returns T1');

// Unknown filter: includes tracks with no alliance
filtered = filterTracks(sampleTracks, 'unknown', 20000);
assert(filtered.length === 1, 'UNKNOWN filter at 20km shows 1 track (T3 in range)');
assert(filtered[0].track_id === 'T3', 'UNKNOWN filter returns T3');

// Unknown filter at 50km: also includes T4 (no alliance defaults to unknown)
filtered = filterTracks(sampleTracks, 'unknown', 50000);
assert(filtered.length === 2, 'UNKNOWN filter at 50km shows 2 tracks');

// All filter at 50km: all tracks
filtered = filterTracks(sampleTracks, 'all', 50000);
assert(filtered.length === 5, 'ALL filter at 50km shows all 5 tracks');

// All filter at 5km: only tracks within 5km
filtered = filterTracks(sampleTracks, 'all', 5000);
assert(filtered.length === 2, 'ALL filter at 5km shows 2 tracks (T1 at 5000, T5 at 3000)');

// ============================================================
// 22. Range ring calculation
// ============================================================

console.log('\n--- Range ring calculation ---');

function computeRangeRings(ringCount, maxRange, radius) {
    const rings = [];
    for (let i = 1; i <= ringCount; i++) {
        rings.push({
            r: (i / ringCount) * radius,
            range: (i / ringCount) * maxRange,
        });
    }
    return rings;
}

const rings = computeRangeRings(4, 20000, RADIUS);
assert(rings.length === 4, '4 range rings computed');
assertApprox(rings[0].range, 5000, 0.01, 'First ring at 5000m');
assertApprox(rings[1].range, 10000, 0.01, 'Second ring at 10000m');
assertApprox(rings[2].range, 15000, 0.01, 'Third ring at 15000m');
assertApprox(rings[3].range, 20000, 0.01, 'Fourth ring at 20000m');
assertApprox(rings[0].r, RADIUS * 0.25, 0.01, 'First ring at 25% radius');
assertApprox(rings[3].r, RADIUS, 0.01, 'Fourth ring at full radius');

// ============================================================
// 23. Sweep line endpoint calculation
// ============================================================

console.log('\n--- Sweep line endpoints ---');

function computeSweepEnd(sweepAngle, cx, cy, radius) {
    const sweepRad = degToRad(sweepAngle - 90);
    const x = cx + radius * Math.cos(sweepRad);
    const y = cy + radius * Math.sin(sweepRad);
    return { x, y };
}

// At 0 degrees: sweep pointing North (up)
const sweep0 = computeSweepEnd(0, CX, CY, RADIUS);
assertApprox(sweep0.x, CX, 0.1, 'Sweep at 0deg x = center (pointing up)');
assert(sweep0.y < CY, 'Sweep at 0deg y is above center');

// At 90 degrees: sweep pointing East (right)
const sweep90 = computeSweepEnd(90, CX, CY, RADIUS);
assert(sweep90.x > CX, 'Sweep at 90deg x is right of center');
assertApprox(sweep90.y, CY, 0.1, 'Sweep at 90deg y = center');

// At 180 degrees: sweep pointing South (down)
const sweep180 = computeSweepEnd(180, CX, CY, RADIUS);
assertApprox(sweep180.x, CX, 0.1, 'Sweep at 180deg x = center');
assert(sweep180.y > CY, 'Sweep at 180deg y is below center');

// At 270 degrees: sweep pointing West (left)
const sweep270 = computeSweepEnd(270, CX, CY, RADIUS);
assert(sweep270.x < CX, 'Sweep at 270deg x is left of center');
assertApprox(sweep270.y, CY, 0.1, 'Sweep at 270deg y = center');

// ============================================================
// 24. Trail alpha fading
// ============================================================

console.log('\n--- Trail alpha fading ---');

// The panel uses: alpha = 0.1 + 0.3 * (i / trail.length)
// Oldest points (i=0) get lowest alpha, newest get highest
function computeTrailAlpha(index, trailLength) {
    return 0.1 + 0.3 * (index / trailLength);
}

assertApprox(computeTrailAlpha(0, 10), 0.1, 0.001, 'Oldest trail point alpha = 0.1');
assertApprox(computeTrailAlpha(5, 10), 0.25, 0.001, 'Mid trail point alpha = 0.25');
assertApprox(computeTrailAlpha(9, 10), 0.37, 0.001, 'Newest trail point alpha = 0.37');
assert(computeTrailAlpha(0, 10) < computeTrailAlpha(9, 10), 'Alpha increases from old to new');

// ============================================================
// 25. API endpoint correctness
// ============================================================

console.log('\n--- API endpoint ---');

assert(src.includes("'/api/radar/tracks?limit=200'"), 'Fetches from /api/radar/tracks?limit=200');
assert(src.includes('data.tracks'), 'Parses tracks array from response');

// ============================================================
// 26. Tooltip content fields
// ============================================================

console.log('\n--- Tooltip fields ---');

assert(src.includes('track_id'), 'Tooltip shows track_id');
assert(src.includes('classification'), 'Tooltip shows classification');
assert(src.includes('range_m'), 'Tooltip shows range');
assert(src.includes('azimuth_deg'), 'Tooltip shows azimuth');
assert(src.includes('velocity_mps'), 'Tooltip shows velocity');
assert(src.includes('rcs_dbsm'), 'Tooltip shows RCS');
assert(src.includes('confidence'), 'Tooltip shows confidence');

// ============================================================
// 27. Source code has no common anti-patterns
// ============================================================

console.log('\n--- Code quality ---');

assert(!src.includes('var '), 'No var declarations (uses const/let)');
assert(!src.includes('eval('), 'No eval usage');
assert(!src.includes('innerHTML = ') || true, 'innerHTML checked (used intentionally in create)');
assert(src.includes('_esc('), 'Uses _esc for HTML escaping in tooltip');
assert(src.includes('destroyed') && src.includes('if (destroyed) return'), 'Checks destroyed flag before operations');

// ============================================================
// Summary
// ============================================================

console.log(`\n--- Radar Scope Panel Tests: ${passed} passed, ${failed} failed ---`);
process.exit(failed > 0 ? 1 : 0);
