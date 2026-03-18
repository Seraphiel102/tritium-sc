// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * TRITIUM-SC Tactical Banner tests
 * Tests the enhanced tactical banner: two-row layout, mode buttons, tool buttons,
 * connection indicators, clock, collapse/expand, threat level, Amy status.
 * Run: node tests/js/test_tactical_banner.js
 */

const fs = require('fs');
const vm = require('vm');

// Simple test runner
let passed = 0, failed = 0;
function assert(cond, msg) {
    if (!cond) { console.error('FAIL:', msg); failed++; }
    else { console.log('PASS:', msg); passed++; }
}

// ============================================================
// DOM + browser mocks
// ============================================================

function createMockElement(tag) {
    const children = [];
    const classList = new Set();
    const eventListeners = {};
    const dataset = {};
    const style = {};
    let _innerHTML = '';
    let _textContent = '';
    let _hidden = false;

    const el = {
        tagName: (tag || 'DIV').toUpperCase(),
        className: '',
        get innerHTML() { return _innerHTML; },
        set innerHTML(val) {
            _innerHTML = val;
            children.length = 0;
        },
        get textContent() { return _textContent; },
        set textContent(val) {
            _textContent = String(val);
            _innerHTML = String(val)
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;');
        },
        style,
        dataset,
        children,
        childNodes: children,
        parentNode: null,
        parentElement: null,
        get hidden() { return _hidden; },
        set hidden(val) { _hidden = !!val; },
        classList: {
            _set: classList,
            add(c) { classList.add(c); el.className = [...classList].join(' '); },
            remove(c) { classList.delete(c); el.className = [...classList].join(' '); },
            toggle(c, force) {
                if (force !== undefined) {
                    if (force) classList.add(c); else classList.delete(c);
                } else {
                    if (classList.has(c)) classList.delete(c); else classList.add(c);
                }
                el.className = [...classList].join(' ');
                return classList.has(c);
            },
            contains(c) { return classList.has(c); },
            forEach(fn) { classList.forEach(fn); },
        },
        addEventListener(ev, fn) {
            if (!eventListeners[ev]) eventListeners[ev] = [];
            eventListeners[ev].push(fn);
        },
        removeEventListener(ev, fn) {
            if (eventListeners[ev]) {
                eventListeners[ev] = eventListeners[ev].filter(f => f !== fn);
            }
        },
        dispatchEvent(ev) {
            const name = typeof ev === 'string' ? ev : ev.type;
            (eventListeners[name] || []).forEach(fn => fn(ev));
        },
        appendChild(child) {
            children.push(child);
            child.parentNode = el;
            child.parentElement = el;
            return child;
        },
        remove() {
            if (el.parentNode) {
                const idx = el.parentNode.children.indexOf(el);
                if (idx >= 0) el.parentNode.children.splice(idx, 1);
            }
        },
        querySelector(sel) { return mockQuerySelector(el, sel); },
        querySelectorAll(sel) { return mockQuerySelectorAll(el, sel); },
        getAttribute(name) { return dataset[name] || null; },
        setAttribute(name, val) { dataset[name] = val; },
        title: '',
        id: '',
        focus() {},
        blur() {},
        click() {
            (eventListeners['click'] || []).forEach(fn => fn({ stopPropagation() {}, target: el }));
        },
    };
    return el;
}

// Minimal querySelector for data-bind and data-tb-mode selectors
function mockQuerySelector(root, sel) {
    const results = mockQuerySelectorAll(root, sel);
    return results[0] || null;
}

function mockQuerySelectorAll(root, sel) {
    // We need to parse the innerHTML of the root to find elements.
    // For our test purposes, we create a simplified DOM from the banner innerHTML.
    // This is a very simplified mock -- we look at _parsedChildren
    if (!root._parsedChildren) return [];
    return root._parsedChildren.filter(el => matchesSelector(el, sel));
}

function matchesSelector(el, sel) {
    // Support: [data-bind="xxx"], [data-tb-mode="xxx"], [data-tb-tool="xxx"],
    //          .className, .classA.classB
    if (!el) return false;

    // Attribute selector
    const attrMatch = sel.match(/\[([a-z-]+)="([^"]+)"\]/);
    if (attrMatch) {
        const [, attr, val] = attrMatch;
        const dsKey = attr.replace(/^data-/, '').replace(/-([a-z])/g, (_, c) => c.toUpperCase());
        return el.dataset[dsKey] === val || el.getAttribute(attr) === val;
    }

    // Class selector
    if (sel.startsWith('.')) {
        const classes = sel.split('.').filter(Boolean);
        return classes.every(c => el.classList.contains(c));
    }

    return false;
}

// ============================================================
// Source code loading + module stubbing
// ============================================================

const SRC_PATH = __dirname + '/../../src/frontend/js/command/tactical-banner.js';
const src = fs.readFileSync(SRC_PATH, 'utf-8');

// Strip ES module syntax for vm evaluation
const cjsSrc = src
    .replace(/^import\s+.*$/gm, '')
    .replace(/^export\s+(const|function|class|let|var)\s/gm, '$1 ')
    .replace(/^export\s+\{[^}]*\}\s*;?\s*$/gm, '');

// Build mock store + event bus
function buildMocks() {
    const storeData = {};
    const storeListeners = {};
    const busListeners = {};

    const TritiumStore = {
        units: new Map(),
        alerts: [],
        amy: { state: 'idle' },
        game: { phase: 'idle' },
        get(key) { return storeData[key]; },
        set(key, val) { storeData[key] = val; },
        on(ev, fn) {
            if (!storeListeners[ev]) storeListeners[ev] = [];
            storeListeners[ev].push(fn);
            return () => {
                storeListeners[ev] = (storeListeners[ev] || []).filter(f => f !== fn);
            };
        },
        _emit(ev) {
            (storeListeners[ev] || []).forEach(fn => fn());
        },
        _storeData: storeData,
    };

    const EventBus = {
        on(ev, fn) {
            if (!busListeners[ev]) busListeners[ev] = [];
            busListeners[ev].push(fn);
        },
        off(ev, fn) {
            if (busListeners[ev]) {
                busListeners[ev] = busListeners[ev].filter(f => f !== fn);
            }
        },
        emit(ev, data) {
            (busListeners[ev] || []).forEach(fn => fn(data));
        },
        _listeners: busListeners,
    };

    return { TritiumStore, EventBus, storeData };
}

// ============================================================
// Build a full mock banner by running the source
// ============================================================

function createBannerFromSource() {
    const mocks = buildMocks();
    const allElements = [];

    // Enhanced createElement that tracks all created elements
    function mockCreateElement(tag) {
        const el = createMockElement(tag);
        allElements.push(el);

        // When innerHTML is set, parse out the child elements
        const origInnerHTMLSetter = Object.getOwnPropertyDescriptor(
            Object.getPrototypeOf(el) === Object.prototype ? el : {},
            'innerHTML'
        );

        let _html = '';
        Object.defineProperty(el, 'innerHTML', {
            get() { return _html; },
            set(val) {
                _html = val;
                el._parsedChildren = parseHTML(val);
            },
        });

        return el;
    }

    // Simple HTML parser that extracts elements with data-* attributes
    function parseHTML(html) {
        const elements = [];
        const tagRegex = /<(button|span|div)\s+([^>]*)>/g;
        let match;
        while ((match = tagRegex.exec(html)) !== null) {
            const tag = match[1];
            const attrs = match[2];
            const el = createMockElement(tag);

            // Parse attributes
            const attrRegex = /([a-z-]+)="([^"]*)"/g;
            let attrMatch;
            while ((attrMatch = attrRegex.exec(attrs)) !== null) {
                const [, name, value] = attrMatch;
                if (name === 'class') {
                    value.split(/\s+/).filter(Boolean).forEach(c => el.classList.add(c));
                } else if (name === 'title') {
                    el.title = value;
                } else if (name.startsWith('data-')) {
                    const dsKey = name.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase());
                    el.dataset[dsKey] = value;
                }
                el.setAttribute(name, value);
            }

            elements.push(el);
        }
        return elements;
    }

    // Mock document
    const container = createMockElement('div');
    const mockDocument = {
        createElement: mockCreateElement,
        getElementById(id) {
            if (id === 'map-mode') return createMockElement('div');
            return null;
        },
        querySelectorAll(sel) { return []; },
        querySelector(sel) { return null; },
    };

    const sandbox = {
        TritiumStore: mocks.TritiumStore,
        EventBus: mocks.EventBus,
        document: mockDocument,
        console,
        Date,
        String,
        Array,
        Map,
        Set,
        Object,
        Math,
        parseInt,
        parseFloat,
        isNaN,
        JSON,
        clearInterval: () => {},
        setInterval: () => 123,
    };

    const script = new vm.Script(`
        ${cjsSrc}
        _result = createTacticalBanner(_container);
    `);

    sandbox._container = container;
    const ctx = vm.createContext(sandbox);
    script.runInContext(ctx);

    return {
        result: sandbox._result,
        container,
        mocks,
        allElements,
        banner: container.children[0],
    };
}

// ============================================================
// Tests
// ============================================================

console.log('--- Tactical Banner Tests ---\n');

// Test 1: Banner created and appended to container
try {
    const { container, banner } = createBannerFromSource();
    assert(container.children.length === 1, 'Banner appended to container');
    assert(banner.id === 'tactical-banner', 'Banner has correct id');
    assert(banner.className.includes('tactical-banner'), 'Banner has correct class');
} catch (e) {
    assert(false, 'Banner creation: ' + e.message);
}

// Test 2: Banner has two rows
try {
    const { banner } = createBannerFromSource();
    const html = banner.innerHTML;
    assert(html.includes('tb-row-top'), 'Banner has top row');
    assert(html.includes('tb-row-tools'), 'Banner has tools row');
} catch (e) {
    assert(false, 'Two rows: ' + e.message);
}

// Test 3: Mode buttons present (OBSERVE, TACTICAL, SETUP)
try {
    const { banner } = createBannerFromSource();
    const html = banner.innerHTML;
    assert(html.includes('data-tb-mode="observe"'), 'Has OBSERVE mode button');
    assert(html.includes('data-tb-mode="tactical"'), 'Has TACTICAL mode button');
    assert(html.includes('data-tb-mode="setup"'), 'Has SETUP mode button');
} catch (e) {
    assert(false, 'Mode buttons: ' + e.message);
}

// Test 4: Tool buttons present (geofence, patrol, waypoint, measure)
try {
    const { banner } = createBannerFromSource();
    const html = banner.innerHTML;
    assert(html.includes('data-tb-tool="geofence"'), 'Has GEOFENCE tool button');
    assert(html.includes('data-tb-tool="patrol"'), 'Has PATROL tool button');
    assert(html.includes('data-tb-tool="waypoint"'), 'Has WAYPOINT tool button');
    assert(html.includes('data-tb-tool="measure"'), 'Has MEASURE tool button');
} catch (e) {
    assert(false, 'Tool buttons: ' + e.message);
}

// Test 5: Connection status indicators present
try {
    const { banner } = createBannerFromSource();
    const html = banner.innerHTML;
    assert(html.includes('data-bind="conn-ws"'), 'Has WS connection indicator');
    assert(html.includes('data-bind="conn-mqtt"'), 'Has MQTT connection indicator');
    assert(html.includes('data-bind="conn-mesh"'), 'Has MESH connection indicator');
    assert(html.includes('data-bind="conn-cam"'), 'Has CAM connection indicator');
} catch (e) {
    assert(false, 'Connection indicators: ' + e.message);
}

// Test 6: Threat level elements present
try {
    const { banner } = createBannerFromSource();
    const html = banner.innerHTML;
    assert(html.includes('data-bind="threat-dot"'), 'Has threat dot');
    assert(html.includes('data-bind="threat-level"'), 'Has threat level display');
} catch (e) {
    assert(false, 'Threat elements: ' + e.message);
}

// Test 7: Amy status elements present
try {
    const { banner } = createBannerFromSource();
    const html = banner.innerHTML;
    assert(html.includes('data-bind="amy-dot"'), 'Has Amy dot');
    assert(html.includes('data-bind="amy-status"'), 'Has Amy status');
} catch (e) {
    assert(false, 'Amy elements: ' + e.message);
}

// Test 8: Clock element present
try {
    const { banner } = createBannerFromSource();
    const html = banner.innerHTML;
    assert(html.includes('data-bind="clock"'), 'Has clock element');
} catch (e) {
    assert(false, 'Clock: ' + e.message);
}

// Test 9: Collapse button present
try {
    const { banner } = createBannerFromSource();
    const html = banner.innerHTML;
    assert(html.includes('data-bind="collapse-btn"'), 'Has collapse button');
    assert(html.includes('tb-collapse-btn'), 'Collapse button has correct class');
} catch (e) {
    assert(false, 'Collapse button: ' + e.message);
}

// Test 10: Target count and alert count elements present
try {
    const { banner } = createBannerFromSource();
    const html = banner.innerHTML;
    assert(html.includes('data-bind="target-count"'), 'Has target count');
    assert(html.includes('data-bind="alert-count"'), 'Has alert count');
} catch (e) {
    assert(false, 'Counts: ' + e.message);
}

// Test 11: Return value has destroy and setMode
try {
    const { result } = createBannerFromSource();
    assert(typeof result.destroy === 'function', 'Has destroy function');
    assert(typeof result.setMode === 'function', 'Has setMode function');
    assert(typeof result.getElement === 'function', 'Has getElement function');
} catch (e) {
    assert(false, 'Return API: ' + e.message);
}

// Test 12: THREAT_LEVELS exported with correct colors
try {
    const sandbox = {};
    const script = new vm.Script(`
        ${cjsSrc}
        _threatLevels = THREAT_LEVELS;
    `);
    const ctx = vm.createContext({
        ...sandbox,
        console,
        TritiumStore: buildMocks().TritiumStore,
        EventBus: buildMocks().EventBus,
    });
    script.runInContext(ctx);
    assert(sandbox._threatLevels || ctx._threatLevels, 'THREAT_LEVELS is defined');
    const tl = ctx._threatLevels;
    assert(tl.GREEN.color === '#05ffa1', 'GREEN threat color correct');
    assert(tl.RED.color === '#ff2a6d', 'RED threat color correct');
    assert(tl.YELLOW.color === '#fcee0a', 'YELLOW threat color correct');
    assert(tl.ORANGE.color === '#ff8800', 'ORANGE threat color correct');
} catch (e) {
    assert(false, 'THREAT_LEVELS: ' + e.message);
}

// Test 13: Tool buttons HTML have keyboard hints
try {
    const { banner } = createBannerFromSource();
    const html = banner.innerHTML;
    assert(html.includes('[G]'), 'Geofence has [G] hint');
    assert(html.includes('[P]'), 'Patrol has [P] hint');
    assert(html.includes('[W]'), 'Waypoint has [W] hint');
    assert(html.includes('[~]'), 'Measure has [~] hint');
} catch (e) {
    assert(false, 'Tool keyboard hints: ' + e.message);
}

// Test 14: Mode buttons have keyboard hints (O, T, S)
try {
    const { banner } = createBannerFromSource();
    const html = banner.innerHTML;
    assert(html.includes('tb-mode-key'), 'Mode buttons have key highlight class');
} catch (e) {
    assert(false, 'Mode keyboard hints: ' + e.message);
}

// Test 15: Connection dots class structure
try {
    const { banner } = createBannerFromSource();
    const html = banner.innerHTML;
    assert(html.includes('tb-conn-dot'), 'Has connection dot elements');
    assert(html.includes('tb-conn-label'), 'Has connection label elements');
} catch (e) {
    assert(false, 'Connection dot structure: ' + e.message);
}

// ============================================================
// Summary
// ============================================================

console.log(`\n--- Results: ${passed} passed, ${failed} failed ---`);
process.exit(failed > 0 ? 1 : 0);
