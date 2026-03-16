// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * TRITIUM Command Center -- Communication Link Map Layer
 *
 * Draws network topology links between edge nodes on the tactical map.
 * Shows mesh peers, WiFi connections, and ESP-NOW links as colored lines
 * with quality indicators (line thickness/opacity = link quality).
 *
 * Data source: fleet heartbeat peer data from /api/fleet/topology
 *
 * Exports: commLinkState, commLinkDraw, commLinkUpdate, commLinkToggle
 */

// ============================================================
// Constants
// ============================================================

const COMM_LINK_COLORS = {
    espnow:  'rgba(0, 240, 255, 0.6)',   // cyan for ESP-NOW
    wifi:    'rgba(5, 255, 161, 0.6)',    // green for WiFi
    ble:     'rgba(138, 100, 255, 0.5)',  // purple for BLE
    lora:    'rgba(252, 238, 10, 0.5)',   // yellow for LoRa
    mqtt:    'rgba(255, 42, 109, 0.4)',   // magenta for MQTT
    unknown: 'rgba(128, 128, 128, 0.3)',  // grey fallback
};

const COMM_NODE_COLOR = '#00f0ff';
const COMM_NODE_RADIUS = 6;
const COMM_LINK_MIN_WIDTH = 1;
const COMM_LINK_MAX_WIDTH = 4;
const COMM_UPDATE_INTERVAL_MS = 5000; // poll fleet topology every 5s

// ============================================================
// Module state
// ============================================================

const commLinkState = {
    visible: false,
    nodes: [],      // { node_id, name, lat, lng, x, y, online, peer_count }
    links: [],      // { source_id, target_id, transport, rssi, quality_score, active }
    lastUpdate: 0,
    fetchTimer: null,
};

// ============================================================
// Data fetch
// ============================================================

/**
 * Fetch topology data from the fleet dashboard API.
 * Parses heartbeat peer data to build node/link lists.
 */
async function commLinkFetch() {
    try {
        const resp = await fetch('/api/fleet/topology');
        if (!resp.ok) return;
        const data = await resp.json();
        if (data.nodes) commLinkState.nodes = data.nodes;
        if (data.links) commLinkState.links = data.links;
        commLinkState.lastUpdate = Date.now();
    } catch (e) {
        // Silent fail — topology is optional
    }
}

/**
 * Start periodic topology polling.
 */
function commLinkStartPolling() {
    if (commLinkState.fetchTimer) return;
    commLinkFetch(); // immediate first fetch
    commLinkState.fetchTimer = setInterval(commLinkFetch, COMM_UPDATE_INTERVAL_MS);
}

/**
 * Stop periodic topology polling.
 */
function commLinkStopPolling() {
    if (commLinkState.fetchTimer) {
        clearInterval(commLinkState.fetchTimer);
        commLinkState.fetchTimer = null;
    }
}

// ============================================================
// Update from WebSocket data
// ============================================================

/**
 * Update topology from a WebSocket message (fleet.topology event).
 * @param {{ nodes: Array, links: Array }} data
 */
function commLinkUpdate(data) {
    if (data && data.nodes) commLinkState.nodes = data.nodes;
    if (data && data.links) commLinkState.links = data.links;
    commLinkState.lastUpdate = Date.now();
}

// ============================================================
// Toggle visibility
// ============================================================

/**
 * Toggle comm-link layer visibility.
 * @returns {boolean} new visibility state
 */
function commLinkToggle() {
    commLinkState.visible = !commLinkState.visible;
    if (commLinkState.visible) {
        commLinkStartPolling();
    } else {
        commLinkStopPolling();
    }
    return commLinkState.visible;
}

// ============================================================
// Drawing
// ============================================================

/**
 * Get link color by transport type.
 * @param {string} transport
 * @returns {string} CSS color
 */
function _getLinkColor(transport) {
    return COMM_LINK_COLORS[transport] || COMM_LINK_COLORS.unknown;
}

/**
 * Compute line width from quality score (0-100).
 * @param {number} quality 0-100
 * @returns {number} line width in pixels
 */
function _getLineWidth(quality) {
    const t = Math.max(0, Math.min(100, quality || 50)) / 100;
    return COMM_LINK_MIN_WIDTH + t * (COMM_LINK_MAX_WIDTH - COMM_LINK_MIN_WIDTH);
}

/**
 * Draw communication links and nodes on the tactical map canvas.
 *
 * @param {CanvasRenderingContext2D} ctx
 * @param {function} worldToScreen - (wx, wy) => { x, y }
 * @param {boolean} visible - whether the layer is visible
 */
function commLinkDraw(ctx, worldToScreen, visible) {
    if (!visible && !commLinkState.visible) return;
    if (commLinkState.links.length === 0 && commLinkState.nodes.length === 0) return;

    ctx.save();

    // Build a position lookup from nodes
    const nodePos = {};
    for (const node of commLinkState.nodes) {
        if (node.x !== undefined && node.y !== undefined) {
            nodePos[node.node_id] = worldToScreen(node.x, node.y);
        }
    }

    // Draw links
    for (const link of commLinkState.links) {
        if (!link.active) continue;
        const srcPos = nodePos[link.source_id];
        const dstPos = nodePos[link.target_id];
        if (!srcPos || !dstPos) continue;

        const color = _getLinkColor(link.transport);
        const width = _getLineWidth(link.quality_score);

        ctx.strokeStyle = color;
        ctx.lineWidth = width;
        ctx.setLineDash([6, 4]);
        ctx.globalAlpha = link.active ? 0.8 : 0.3;

        ctx.beginPath();
        ctx.moveTo(srcPos.x, srcPos.y);
        ctx.lineTo(dstPos.x, dstPos.y);
        ctx.stroke();

        // Draw quality label at midpoint for links with low quality
        if (link.quality_score !== undefined && link.quality_score < 40) {
            const mx = (srcPos.x + dstPos.x) / 2;
            const my = (srcPos.y + dstPos.y) / 2;
            ctx.setLineDash([]);
            ctx.globalAlpha = 0.9;
            ctx.fillStyle = '#ff2a6d';
            ctx.font = 'bold 9px "JetBrains Mono", monospace';
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            ctx.fillText(link.quality_score + '%', mx, my - 8);
        }
    }

    ctx.setLineDash([]);
    ctx.globalAlpha = 1.0;

    // Draw nodes
    for (const node of commLinkState.nodes) {
        const sp = nodePos[node.node_id];
        if (!sp) continue;

        const isOnline = node.online !== false;

        // Outer glow
        ctx.fillStyle = isOnline ? COMM_NODE_COLOR : 'rgba(128, 128, 128, 0.5)';
        ctx.globalAlpha = 0.3;
        ctx.beginPath();
        ctx.arc(sp.x, sp.y, COMM_NODE_RADIUS + 3, 0, Math.PI * 2);
        ctx.fill();

        // Inner dot
        ctx.globalAlpha = isOnline ? 1.0 : 0.5;
        ctx.fillStyle = isOnline ? COMM_NODE_COLOR : '#666';
        ctx.beginPath();
        ctx.arc(sp.x, sp.y, COMM_NODE_RADIUS, 0, Math.PI * 2);
        ctx.fill();

        // Label
        ctx.fillStyle = '#00f0ff';
        ctx.globalAlpha = 0.9;
        ctx.font = '9px "JetBrains Mono", monospace';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'top';
        const label = node.name || node.node_id;
        ctx.fillText(label, sp.x, sp.y + COMM_NODE_RADIUS + 3);

        // Peer count badge
        if (node.peer_count > 0) {
            ctx.fillStyle = '#05ffa1';
            ctx.font = 'bold 8px "JetBrains Mono", monospace';
            ctx.textBaseline = 'bottom';
            ctx.fillText(node.peer_count + 'p', sp.x, sp.y - COMM_NODE_RADIUS - 2);
        }
    }

    ctx.restore();
}

// ============================================================
// Exports
// ============================================================

if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
        COMM_LINK_COLORS,
        COMM_NODE_COLOR,
        commLinkState,
        commLinkDraw,
        commLinkUpdate,
        commLinkToggle,
        commLinkFetch,
        commLinkStartPolling,
        commLinkStopPolling,
    };
}
