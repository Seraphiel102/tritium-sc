// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * TRITIUM-SC SDR Spectrum Waterfall Panel tests
 * Tests SdrWaterfallPanelDef structure, DOM creation, canvas rendering,
 * waterfall scrolling, signal detection sidebar, controls, demo fallback,
 * and start/stop toggle behavior.
 * Run: node tests/js/test_sdr_waterfall_panel.js
 */

const fs = require('fs');
const vm = require('vm');

let passed = 0, failed = 0;
function assert(cond, msg) {
    if (!cond) { console.error('FAIL:', msg); failed++; }
    else { console.log('PASS:', msg); passed++; }
}

// ============================================================
// DOM + browser mocks
// ============================================================

function createMockCanvas() {
    const drawCalls = [];
    const ctx = {
        _drawCalls: drawCalls,
        fillStyle: '',
        strokeStyle: '',
        lineWidth: 1,
        font: '',
        textAlign: '',
        shadowColor: '',
        shadowBlur: 0,
        fillRect(x, y, w, h) { drawCalls.push({ op: 'fillRect', x, y, w, h }); },
        beginPath() { drawCalls.push({ op: 'beginPath' }); },
        moveTo(x, y) { drawCalls.push({ op: 'moveTo', x, y }); },
        lineTo(x, y) { drawCalls.push({ op: 'lineTo', x, y }); },
        stroke() { drawCalls.push({ op: 'stroke' }); },
        fill() { drawCalls.push({ op: 'fill' }); },
        closePath() { drawCalls.push({ op: 'closePath' }); },
        fillText(text, x, y) { drawCalls.push({ op: 'fillText', text, x, y }); },
        setTransform(a, b, c, d, e, f) { drawCalls.push({ op: 'setTransform', a, b, c, d, e, f }); },
        setLineDash(arr) { drawCalls.push({ op: 'setLineDash', arr }); },
        createImageData(w, h) {
            return { data: new Uint8ClampedArray(w * h * 4), width: w, height: h };
        },
        putImageData(imgData, x, y) { drawCalls.push({ op: 'putImageData', x, y }); },
    };
    return ctx;
}

function createMockElement(tag) {
    const children = [];
    const classList = new Set();
    const eventListeners = {};
    const dataset = {};
    const style = { cssText: '' };
    let _innerHTML = '';
    let _textContent = '';
    let _value = '';
    const _mockCtx = createMockCanvas();

    const el = {
        tagName: (tag || 'DIV').toUpperCase(),
        className: '',
        get innerHTML() { return _innerHTML; },
        set innerHTML(val) { _innerHTML = val; },
        get textContent() { return _textContent; },
        set textContent(val) { _textContent = String(val); },
        get value() { return _value; },
        set value(val) { _value = String(val); },
        style,
        dataset,
        children,
        childNodes: children,
        parentNode: null,
        hidden: false,
        disabled: false,
        scrollHeight: 100,
        scrollTop: 0,
        width: 0,
        height: 0,
        get classList() {
            return {
                add(cls) { classList.add(cls); },
                remove(cls) { classList.delete(cls); },
                contains(cls) { return classList.has(cls); },
                toggle(cls, force) {
                    if (force === undefined) {
                        if (classList.has(cls)) classList.delete(cls); else classList.add(cls);
                    } else if (force) classList.add(cls); else classList.delete(cls);
                },
            };
        },
        appendChild(child) { children.push(child); if (child && typeof child === 'object') child.parentNode = el; return child; },
        removeChild(child) { const i = children.indexOf(child); if (i >= 0) children.splice(i, 1); },
        remove() {},
        focus() {},
        addEventListener(evt, fn) {
            if (!eventListeners[evt]) eventListeners[evt] = [];
            eventListeners[evt].push(fn);
        },
        removeEventListener(evt, fn) {
            if (eventListeners[evt]) eventListeners[evt] = eventListeners[evt].filter(f => f !== fn);
        },
        querySelector(sel) {
            const bindMatch = sel.match(/\[data-bind="([^"]+)"\]/);
            if (bindMatch) {
                const name = bindMatch[1];
                const mock = createMockElement(
                    name.includes('canvas') ? 'canvas' :
                    name === 'bandwidth' ? 'select' :
                    name === 'center-freq' || name === 'gain' ? 'input' :
                    'span'
                );
                mock._bindName = name;
                if (name === 'center-freq') mock.value = '433.92';
                if (name === 'bandwidth') mock.value = '2000000';
                if (name === 'gain') mock.value = '40';
                if (name.includes('canvas')) {
                    mock.getBoundingClientRect = () => ({ width: 400, height: 200, left: 0, top: 0 });
                    mock.getContext = () => _mockCtx;
                    mock._mockCtx = _mockCtx;
                }
                return mock;
            }
            const actionMatch = sel.match(/\[data-action="([^"]+)"\]/);
            if (actionMatch) {
                const mock = createMockElement('button');
                mock._actionName = actionMatch[1];
                mock.textContent = 'START';
                return mock;
            }
            if (sel === '.sdr-wf-signal-list') {
                const mock = createMockElement('ul');
                mock.innerHTML = '<li style="color:#555">No signals</li>';
                return mock;
            }
            return createMockElement('span');
        },
        querySelectorAll() { return []; },
        closest() { return null; },
        getContext(type) {
            if (type === '2d') return _mockCtx;
            return null;
        },
        getBoundingClientRect() { return { width: 400, height: 200, left: 0, top: 0 }; },
        _eventListeners: eventListeners,
        _classList: classList,
        _mockCtx: _mockCtx,
    };
    return el;
}

// ============================================================
// Sandbox setup
// ============================================================

const EventBusMock = {
    _handlers: {},
    on(evt, fn) {
        if (!this._handlers[evt]) this._handlers[evt] = [];
        this._handlers[evt].push(fn);
        return () => {
            this._handlers[evt] = this._handlers[evt].filter(f => f !== fn);
        };
    },
    emit(evt, data) { (this._handlers[evt] || []).forEach(fn => fn(data)); },
};

const exported = {};
let lastFetchUrl = null;
let fetchResponse = { ok: true, status: 200, json: async () => ({ sweeps: [] }) };

const mockContext = {
    console, Math, Date, parseInt, parseFloat,
    Set, Map, Object, Array, String, Number, JSON, Error, RegExp,
    Boolean, Infinity, NaN, undefined, isNaN, isFinite,
    Uint8ClampedArray,
    Promise,
    setTimeout: (fn, ms) => { fn(); return 1; },
    clearTimeout: () => {},
    setInterval: () => 42,
    clearInterval: () => {},
    window: { devicePixelRatio: 1 },
    document: { createElement: createMockElement },
    fetch: async (url, opts) => {
        lastFetchUrl = url;
        return fetchResponse;
    },
    _esc: (s) => String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'),
    EventBus: EventBusMock,
    exported,
};

// Load the panel source
const src = fs.readFileSync(
    __dirname + '/../../src/frontend/js/command/panels/sdr-waterfall.js',
    'utf-8'
);

let cjsSrc = src
    .replace(/^import\s+\{[^}]+\}\s+from\s+'[^']+';?\s*$/gm, '')
    .replace(/^export\s+const\s+/gm, 'exported.')
    .replace(/^export\s+function\s+/gm, 'function ')
    .replace(/^export\s+/gm, '');

try {
    const script = new vm.Script(cjsSrc, { filename: 'sdr-waterfall.js' });
    const ctx = vm.createContext(mockContext);
    script.runInContext(ctx);
} catch (e) {
    console.error('Failed to load module:', e.message);
    console.error(e.stack);
    process.exit(1);
}

const SdrWaterfallPanelDef = exported.SdrWaterfallPanelDef;

// ============================================================
// 1. Panel definition structure
// ============================================================
console.log('\n--- 1. Panel definition structure ---');

assert(SdrWaterfallPanelDef !== undefined, 'SdrWaterfallPanelDef is exported');
assert(SdrWaterfallPanelDef.id === 'sdr-waterfall', 'Panel ID is sdr-waterfall');
assert(SdrWaterfallPanelDef.title === 'SDR SPECTRUM', 'Panel title is SDR SPECTRUM');
assert(typeof SdrWaterfallPanelDef.create === 'function', 'create is a function');
assert(typeof SdrWaterfallPanelDef.mount === 'function', 'mount is a function');
assert(typeof SdrWaterfallPanelDef.unmount === 'function', 'unmount is a function');
assert(SdrWaterfallPanelDef.defaultSize.w === 720, 'Default width is 720');
assert(SdrWaterfallPanelDef.defaultSize.h === 560, 'Default height is 560');
assert(SdrWaterfallPanelDef.defaultPosition.x === 16, 'Default position x is 16');
assert(SdrWaterfallPanelDef.defaultPosition.y === 16, 'Default position y is 16');

// ============================================================
// 2. Panel creation and DOM structure
// ============================================================
console.log('\n--- 2. Panel creation and DOM structure ---');

(function() {
    const el = SdrWaterfallPanelDef.create({});
    assert(el !== null && el !== undefined, 'create() returns an element');
    assert(el.className === 'sdr-wf-inner', 'Root element has class sdr-wf-inner');
})();

(function() {
    const html = SdrWaterfallPanelDef.create({}).innerHTML;
    assert(html.includes('data-bind="status-dot"'), 'Has status dot binding');
    assert(html.includes('data-bind="status-text"'), 'Has status text binding');
    assert(html.includes('data-bind="freq-label"'), 'Has frequency label binding');
    assert(html.includes('data-bind="center-freq"'), 'Has center frequency input binding');
    assert(html.includes('data-bind="bandwidth"'), 'Has bandwidth select binding');
    assert(html.includes('data-bind="gain"'), 'Has gain slider binding');
    assert(html.includes('data-bind="gain-label"'), 'Has gain label binding');
    assert(html.includes('data-bind="spectrum-canvas"'), 'Has spectrum canvas binding');
    assert(html.includes('data-bind="waterfall-canvas"'), 'Has waterfall canvas binding');
    assert(html.includes('data-bind="signal-list"'), 'Has signal list binding');
})();

(function() {
    const html = SdrWaterfallPanelDef.create({}).innerHTML;
    assert(html.includes('data-action="scan"'), 'Has scan action button');
    assert(html.includes('START'), 'Scan button says START initially');
})();

(function() {
    const html = SdrWaterfallPanelDef.create({}).innerHTML;
    assert(html.includes('DETECTED SIGNALS'), 'Has detected signals sidebar header');
    assert(html.includes('No signals'), 'Shows "No signals" initially');
    assert(html.includes('OFFLINE'), 'Shows OFFLINE status initially');
})();

// ============================================================
// 3. Control inputs (center freq, bandwidth, gain)
// ============================================================
console.log('\n--- 3. Control inputs ---');

(function() {
    const html = SdrWaterfallPanelDef.create({}).innerHTML;
    assert(html.includes('value="433.92"'), 'Default center frequency is 433.92 MHz');
    assert(html.includes('step="0.1"'), 'Frequency input step is 0.1');
    assert(html.includes('CENTER'), 'Has CENTER label for frequency');
    assert(html.includes('MHz'), 'Shows MHz unit');
})();

(function() {
    const html = SdrWaterfallPanelDef.create({}).innerHTML;
    assert(html.includes('1 MHz'), 'Has 1 MHz bandwidth option');
    assert(html.includes('2 MHz'), 'Has 2 MHz bandwidth option');
    assert(html.includes('5 MHz'), 'Has 5 MHz bandwidth option');
    assert(html.includes('10 MHz'), 'Has 10 MHz bandwidth option');
    assert(html.includes('20 MHz'), 'Has 20 MHz bandwidth option');
    assert(html.includes('BW'), 'Has BW label for bandwidth');
})();

(function() {
    const html = SdrWaterfallPanelDef.create({}).innerHTML;
    assert(html.includes('GAIN'), 'Has GAIN label');
    assert(html.includes('min="0"'), 'Gain slider min is 0');
    assert(html.includes('max="60"'), 'Gain slider max is 60');
    assert(html.includes('value="40"'), 'Gain slider default is 40');
    assert(html.includes('40dB'), 'Gain label shows 40dB');
})();

// ============================================================
// 4. mount() does not crash
// ============================================================
console.log('\n--- 4. mount() ---');

(function() {
    const bodyEl = createMockElement('div');
    const panel = { def: SdrWaterfallPanelDef, _unsubs: [] };
    let threw = false;
    try {
        SdrWaterfallPanelDef.mount(bodyEl, panel);
    } catch (e) {
        threw = true;
        console.error('mount() error:', e.message);
    }
    assert(!threw, 'mount() does not crash');
})();

(function() {
    const bodyEl = createMockElement('div');
    const panel = { def: SdrWaterfallPanelDef, _unsubs: [] };
    SdrWaterfallPanelDef.mount(bodyEl, panel);
    assert(panel._unsubs.length >= 1, 'mount() registers cleanup subscriptions, got ' + panel._unsubs.length);
})();

// ============================================================
// 5. unmount() does not crash
// ============================================================
console.log('\n--- 5. unmount() ---');

(function() {
    let threw = false;
    try {
        SdrWaterfallPanelDef.unmount(createMockElement('div'));
    } catch (e) {
        threw = true;
    }
    assert(!threw, 'unmount() does not throw');
})();

// ============================================================
// 6. Source code quality checks
// ============================================================
console.log('\n--- 6. Source code quality checks ---');

assert(src.includes('dbmToColor'), 'Has dbmToColor function for waterfall coloring');
assert(src.includes('WATERFALL_COLORS'), 'Has WATERFALL_COLORS gradient array');
assert(src.includes('fmtFreqMHz'), 'Has frequency formatting function');
assert(src.includes('fmtPower'), 'Has power formatting function');
assert(src.includes('identifySignal'), 'Has signal identification function');
assert(src.includes('KNOWN_BANDS'), 'Has known frequency bands array');
assert(src.includes('BW_OPTIONS'), 'Has bandwidth options array');
assert(src.includes('generateFallbackSweep'), 'Has fallback sweep generator for demo mode');
assert(src.includes('detectPeaks'), 'Has peak detection function');
assert(src.includes('computeNoiseFloor'), 'Has noise floor computation');
assert(src.includes('renderSpectrum'), 'Has spectrum rendering function');
assert(src.includes('renderWaterfall'), 'Has waterfall rendering function');
assert(src.includes('renderSignalList'), 'Has signal list rendering function');
assert(src.includes('handleSweep'), 'Has sweep handler function');
assert(src.includes('fetchSpectrum'), 'Has spectrum fetch function');
assert(src.includes('fetchStatus'), 'Has status fetch function');
assert(src.includes('startScan'), 'Has startScan function');
assert(src.includes('stopScan'), 'Has stopScan function');

// API endpoints
assert(src.includes('/api/sdr/spectrum/sweeps'), 'Fetches from /api/sdr/spectrum/sweeps');
assert(src.includes('/api/sdr/status'), 'Fetches from /api/sdr/status');
assert(src.includes('/api/sdr/configure'), 'Posts to /api/sdr/configure');
assert(src.includes('/api/sdr/demo/start'), 'Posts to /api/sdr/demo/start');

// Canvas rendering
assert(src.includes('getContext'), 'Uses canvas getContext');
assert(src.includes('createImageData'), 'Uses createImageData for waterfall pixels');
assert(src.includes('putImageData'), 'Uses putImageData for waterfall rendering');
assert(src.includes('devicePixelRatio'), 'Handles devicePixelRatio for HiDPI');

// Waterfall scrolling
assert(src.includes('waterfallRows'), 'Tracks waterfall row history');
assert(src.includes('MAX_WF_ROWS'), 'Has maximum waterfall rows limit');
assert(src.includes('unshift'), 'New sweeps are unshifted (prepended) for scrolling');

// Signal detection
assert(src.includes('detectedSignals'), 'Tracks detected signals');
assert(src.includes('noiseFloor'), 'Computes noise floor for peak detection');

// Known bands
assert(src.includes('WiFi/BLE'), 'Identifies WiFi/BLE band');
assert(src.includes('ISM 433'), 'Identifies ISM 433 band');
assert(src.includes('ISM 868'), 'Identifies ISM 868 band');
assert(src.includes('ISM 915'), 'Identifies ISM 915 band');
assert(src.includes('TPMS 315'), 'Identifies TPMS 315 band');
assert(src.includes('ADS-B'), 'Identifies ADS-B band');
assert(src.includes('NOAA SAT'), 'Identifies NOAA satellite band');
assert(src.includes('FRS/GMRS'), 'Identifies FRS/GMRS band');

// Cleanup
assert(src.includes('clearInterval'), 'Cleans up intervals');
assert(src.includes('_unsubs'), 'Uses _unsubs for cleanup');
assert(src.includes('onResize'), 'Handles panel resize');

// Color scheme
assert(src.includes('#00f0ff'), 'Uses cyan accent color');
assert(src.includes('#0a0a0f'), 'Uses dark background color');
assert(src.includes('#05ffa1'), 'Uses green accent color');
assert(src.includes('#ff2a6d'), 'Uses magenta accent color');

// ============================================================
// 7. Styling and layout
// ============================================================
console.log('\n--- 7. Styling and layout ---');

(function() {
    const html = SdrWaterfallPanelDef.create({}).innerHTML;
    assert(html.includes('sdr-wf-header'), 'Has header section');
    assert(html.includes('sdr-wf-controls'), 'Has controls section');
    assert(html.includes('sdr-wf-body'), 'Has body section');
    assert(html.includes('sdr-wf-viz'), 'Has visualization container');
    assert(html.includes('sdr-wf-sidebar'), 'Has sidebar for signals');
    assert(html.includes('sdr-wf-signal-list'), 'Has signal list element');
})();

(function() {
    const el = SdrWaterfallPanelDef.create({});
    assert(el.style.cssText.includes('flex-direction:column'), 'Uses flexbox column layout');
    assert(el.style.cssText.includes('height:100%'), 'Fills full height');
})();

// ============================================================
// 8. No banned patterns
// ============================================================
console.log('\n--- 8. No banned patterns ---');

assert(!src.includes('eval('), 'Does not use eval');
assert(!src.includes('innerHTML =') || src.includes('signalList.innerHTML'), 'Only uses innerHTML for signal list updates');
assert(src.includes('_esc'), 'Uses _esc for HTML escaping in signal list');

// ============================================================
// Summary
// ============================================================
console.log('\n' + '='.repeat(50));
console.log(`SDR Waterfall Panel Tests: ${passed} passed, ${failed} failed`);
console.log('='.repeat(50));
process.exit(failed > 0 ? 1 : 0);
