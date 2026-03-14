// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * TRITIUM-SC -- Communication Link Map Layer tests
 * Run: node tests/js/test_comm_link_layer.js
 *
 * Tests comm link drawing, toggle, update, and color constants.
 */

const fs = require('fs');
const vm = require('vm');

// Simple test runner
let passed = 0, failed = 0;
function assert(cond, msg) {
    if (!cond) { console.error('FAIL:', msg); failed++; }
    else { console.log('PASS:', msg); passed++; }
}
function assertEqual(a, b, msg) {
    assert(a === b, msg + ` (got ${JSON.stringify(a)}, expected ${JSON.stringify(b)})`);
}

// ---------------------------------------------------------------------------
// Load comm-link-layer.js into a sandboxed context
// ---------------------------------------------------------------------------

const code = fs.readFileSync(__dirname + '/../../src/frontend/js/command/comm-link-layer.js', 'utf8');

function createMockCtx() {
    const calls = [];
    return {
        calls,
        save() { calls.push({ op: 'save' }); },
        restore() { calls.push({ op: 'restore' }); },
        beginPath() { calls.push({ op: 'beginPath' }); },
        arc(x, y, r, a1, a2) { calls.push({ op: 'arc', x, y, r }); },
        fill() { calls.push({ op: 'fill' }); },
        stroke() { calls.push({ op: 'stroke' }); },
        fillText(text, x, y) { calls.push({ op: 'fillText', text, x, y }); },
        moveTo(x, y) { calls.push({ op: 'moveTo', x, y }); },
        lineTo(x, y) { calls.push({ op: 'lineTo', x, y }); },
        setLineDash(d) { calls.push({ op: 'setLineDash', d }); },
        closePath() { calls.push({ op: 'closePath' }); },
        fillStyle: '',
        strokeStyle: '',
        lineWidth: 1,
        globalAlpha: 1,
        font: '',
        textAlign: 'center',
        textBaseline: 'middle',
    };
}

// Stub fetch for Node.js
const fakeModule = { exports: {} };
const ctx = vm.createContext({
    Math, Date, console, Map, Array, Object, Number, Infinity, Boolean, JSON,
    parseInt, parseFloat, isNaN, isFinite, undefined,
    setInterval: () => 999,
    clearInterval: () => {},
    fetch: () => Promise.resolve({ ok: false }),
    module: fakeModule,
});
vm.runInContext(code, ctx);

const {
    COMM_LINK_COLORS,
    COMM_NODE_COLOR,
    commLinkState,
    commLinkDraw,
    commLinkUpdate,
    commLinkToggle,
} = fakeModule.exports;

// ============================================================
// Constants
// ============================================================

console.log('\n--- Constants ---');

(function testTransportColors() {
    assert(typeof COMM_LINK_COLORS.espnow === 'string', 'ESP-NOW color defined');
    assert(typeof COMM_LINK_COLORS.wifi === 'string', 'WiFi color defined');
    assert(typeof COMM_LINK_COLORS.ble === 'string', 'BLE color defined');
    assert(typeof COMM_LINK_COLORS.lora === 'string', 'LoRa color defined');
    assert(typeof COMM_LINK_COLORS.mqtt === 'string', 'MQTT color defined');
})();

(function testNodeColor() {
    assertEqual(COMM_NODE_COLOR, '#00f0ff', 'Node color is cyan');
})();

// ============================================================
// commLinkUpdate
// ============================================================

console.log('\n--- Update ---');

(function testUpdateSetsData() {
    commLinkUpdate({
        nodes: [{ node_id: 'n1', x: 10, y: 20 }],
        links: [{ source_id: 'n1', target_id: 'n2', transport: 'espnow', active: true }],
    });
    assertEqual(commLinkState.nodes.length, 1, 'Nodes updated');
    assertEqual(commLinkState.links.length, 1, 'Links updated');
    assert(commLinkState.lastUpdate > 0, 'lastUpdate set');
})();

(function testUpdateNullSafe() {
    commLinkState.nodes = [];
    commLinkState.links = [];
    commLinkUpdate(null);
    assertEqual(commLinkState.nodes.length, 0, 'Null update does not crash');
})();

(function testUpdatePartialData() {
    commLinkUpdate({ nodes: [{ node_id: 'x' }] });
    assertEqual(commLinkState.nodes.length, 1, 'Partial update sets nodes');
    assertEqual(commLinkState.links.length, 0, 'Links unchanged on partial update');
})();

// ============================================================
// commLinkToggle
// ============================================================

console.log('\n--- Toggle ---');

(function testToggleOnOff() {
    commLinkState.visible = false;
    const r1 = commLinkToggle();
    assertEqual(r1, true, 'Toggle turns on');
    assertEqual(commLinkState.visible, true, 'State is visible');
    const r2 = commLinkToggle();
    assertEqual(r2, false, 'Toggle turns off');
    assertEqual(commLinkState.visible, false, 'State is hidden');
})();

// ============================================================
// commLinkDraw
// ============================================================

console.log('\n--- Draw ---');

(function testDrawEmpty() {
    commLinkState.nodes = [];
    commLinkState.links = [];
    const mockCtx = createMockCtx();
    const w2s = (wx, wy) => ({ x: wx * 10, y: wy * 10 });
    commLinkDraw(mockCtx, w2s, true);
    // No crash
    assert(true, 'Drawing empty does not crash');
})();

(function testDrawNodesAndLinks() {
    commLinkState.visible = true;
    commLinkState.nodes = [
        { node_id: 'a', x: 10, y: 20, online: true, peer_count: 2, name: 'Alpha' },
        { node_id: 'b', x: 30, y: 40, online: true, peer_count: 1, name: 'Beta' },
    ];
    commLinkState.links = [
        { source_id: 'a', target_id: 'b', transport: 'espnow', quality_score: 80, active: true },
    ];
    const mockCtx = createMockCtx();
    const w2s = (wx, wy) => ({ x: wx * 10, y: wy * 10 });
    commLinkDraw(mockCtx, w2s, true);

    const arcs = mockCtx.calls.filter(c => c.op === 'arc');
    assert(arcs.length >= 2, 'At least 2 arcs drawn (nodes)');

    const lines = mockCtx.calls.filter(c => c.op === 'lineTo');
    assert(lines.length >= 1, 'At least 1 link line drawn');

    const labels = mockCtx.calls.filter(c => c.op === 'fillText');
    assert(labels.length >= 2, 'Node labels drawn');
})();

(function testDrawSkipsInactiveLinks() {
    commLinkState.visible = true;
    commLinkState.nodes = [
        { node_id: 'a', x: 10, y: 20 },
        { node_id: 'b', x: 30, y: 40 },
    ];
    commLinkState.links = [
        { source_id: 'a', target_id: 'b', transport: 'wifi', active: false },
    ];
    const mockCtx = createMockCtx();
    const w2s = (wx, wy) => ({ x: wx * 10, y: wy * 10 });
    commLinkDraw(mockCtx, w2s, true);

    const lines = mockCtx.calls.filter(c => c.op === 'lineTo');
    assertEqual(lines.length, 0, 'No lines for inactive links');
})();

(function testDrawHiddenLayer() {
    commLinkState.visible = false;
    commLinkState.nodes = [{ node_id: 'a', x: 10, y: 20 }];
    const mockCtx = createMockCtx();
    const w2s = (wx, wy) => ({ x: wx * 10, y: wy * 10 });
    commLinkDraw(mockCtx, w2s, false);

    const arcs = mockCtx.calls.filter(c => c.op === 'arc');
    assertEqual(arcs.length, 0, 'No arcs when layer is hidden');
})();

(function testDrawLowQualityLabel() {
    commLinkState.visible = true;
    commLinkState.nodes = [
        { node_id: 'a', x: 10, y: 20 },
        { node_id: 'b', x: 30, y: 40 },
    ];
    commLinkState.links = [
        { source_id: 'a', target_id: 'b', transport: 'espnow', quality_score: 20, active: true },
    ];
    const mockCtx = createMockCtx();
    const w2s = (wx, wy) => ({ x: wx * 10, y: wy * 10 });
    commLinkDraw(mockCtx, w2s, true);

    // Should draw a quality percentage label for low quality
    const labels = mockCtx.calls.filter(c => c.op === 'fillText' && typeof c.text === 'string' && c.text.includes('%'));
    assert(labels.length >= 1, 'Quality percentage label drawn for low quality link');
})();

// ============================================================
// Summary
// ============================================================

console.log(`\n=== COMM LINK LAYER: ${passed} passed, ${failed} failed ===`);
process.exit(failed > 0 ? 1 : 0);
