// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * TRITIUM Command Center -- Mesh Radio Map Layer
 *
 * Dedicated draw layer for Meshtastic mesh radio nodes on the tactical map.
 * Draws protocol-specific icons (M=Meshtastic, C=MeshCore, W=Web) sized by
 * actual SNR, link lines between nodes that share real neighbor data colored
 * by actual SNR, and hop count labels on links.
 *
 * NO estimated coverage circles. Only renders what the mesh network actually
 * reports: real nodes, real neighbor relationships, real signal quality.
 *
 * Fetches live node data from /api/meshtastic/nodes?has_gps=true with
 * 30-second auto-refresh. Sub-layers: nodes, links.
 *
 * Exports: meshDrawNodes, meshGetIconForProtocol, meshShouldDrawLink,
 *          meshState, meshFetchNodes, meshGetNodeCount,
 *          MESH_PROTOCOL_ICONS, MESH_NODE_COLOR, MESH_LINK_COLOR,
 *          MESH_LINK_RANGE
 */

// ============================================================
// Constants
// ============================================================

const MESH_PROTOCOL_ICONS = {
    meshtastic: 'M',
    meshcore: 'C',
    web: 'W',
};

const MESH_NODE_COLOR = '#00d4aa';      // teal-green for mesh nodes
const MESH_LINK_COLOR = 'rgba(0, 212, 170, 0.25)';
const MESH_LINK_RANGE = 500;             // meters -- max link draw distance (fallback)

// Link quality color scale (SNR-based)
const MESH_LINK_QUALITY = {
    excellent: 'rgba(5, 255, 161, 0.5)',   // green -- SNR > 5
    good:      'rgba(0, 212, 170, 0.35)',  // teal -- SNR 0..5
    fair:      'rgba(252, 238, 10, 0.3)',  // yellow -- SNR -5..0
    poor:      'rgba(255, 42, 109, 0.25)', // magenta -- SNR < -5
};

// ============================================================
// Module state
// ============================================================

const meshState = {
    visible: true,
    showNodes: true,
    showLinks: true,
    opacity: 1.0,
    // Fetched API nodes (GPS-enabled Meshtastic nodes)
    apiNodes: [],
    apiNodeCount: 0,
    apiTotalCount: 0,
    lastFetch: 0,
    fetchInterval: null,
};

// ============================================================
// API fetch
// ============================================================

/**
 * Fetch Meshtastic nodes with GPS from the API.
 * Updates meshState.apiNodes and meshState.apiNodeCount.
 * @returns {Promise<void>}
 */
function meshFetchNodes() {
    return fetch('/api/meshtastic/nodes?has_gps=true&sort_by=snr')
        .then(function(r) { return r.ok ? r.json() : { nodes: [], count: 0, total: 0 }; })
        .then(function(data) {
            meshState.apiNodes = data.nodes || [];
            meshState.apiNodeCount = data.count || 0;
            meshState.apiTotalCount = data.total || 0;
            meshState.lastFetch = Date.now();
        })
        .catch(function() {
            // Silently fail -- API may not be available
        });
}

/**
 * Start 30-second auto-refresh of mesh node data.
 */
function meshStartAutoRefresh() {
    if (meshState.fetchInterval) return;
    meshFetchNodes();
    meshState.fetchInterval = setInterval(meshFetchNodes, 30000);
}

/**
 * Stop auto-refresh.
 */
function meshStopAutoRefresh() {
    if (meshState.fetchInterval) {
        clearInterval(meshState.fetchInterval);
        meshState.fetchInterval = null;
    }
}

/**
 * Get current GPS node count for display in layer toggle label.
 * @returns {number}
 */
function meshGetNodeCount() {
    return meshState.apiNodeCount;
}

// ============================================================
// Icon resolution
// ============================================================

/**
 * Return the single-character icon for a mesh protocol.
 * Falls back to '?' for unknown protocols.
 * @param {string} protocol
 * @returns {string}
 */
function meshGetIconForProtocol(protocol) {
    return MESH_PROTOCOL_ICONS[protocol] || '?';
}

// ============================================================
// Link distance check
// ============================================================

/**
 * Check if two nodes are within range to draw a link.
 * @param {{ x: number, y: number }} a
 * @param {{ x: number, y: number }} b
 * @param {number} range
 * @returns {boolean}
 */
function meshShouldDrawLink(a, b, range) {
    const dx = a.x - b.x;
    const dy = a.y - b.y;
    return (dx * dx + dy * dy) <= range * range;
}

// ============================================================
// Link quality
// ============================================================

/**
 * Get link color based on average SNR of two nodes.
 * @param {object} a - node with optional snr field
 * @param {object} b - node with optional snr field
 * @returns {string} CSS color
 */
function meshGetLinkColor(a, b) {
    const snrA = (a.metadata && a.metadata.snr) || a.snr;
    const snrB = (b.metadata && b.metadata.snr) || b.snr;
    if (snrA === undefined && snrB === undefined) return MESH_LINK_COLOR;
    const avgSnr = (snrA !== undefined && snrB !== undefined)
        ? (snrA + snrB) / 2
        : (snrA !== undefined ? snrA : snrB);
    if (avgSnr > 5) return MESH_LINK_QUALITY.excellent;
    if (avgSnr > 0) return MESH_LINK_QUALITY.good;
    if (avgSnr > -5) return MESH_LINK_QUALITY.fair;
    return MESH_LINK_QUALITY.poor;
}

/**
 * Get node icon radius based on SNR quality.
 * Better SNR = larger icon (6..12px range).
 * @param {object} node
 * @returns {number} radius in pixels
 */
function meshGetNodeRadius(node) {
    const snr = (node.metadata && node.metadata.snr) || node.snr;
    if (snr === undefined) return 8;
    // Clamp SNR to -20..+20 range, map to 6..12
    const clamped = Math.max(-20, Math.min(20, snr));
    return 6 + ((clamped + 20) / 40) * 6;
}

// ============================================================
// Neighbor lookup
// ============================================================

/**
 * Build a map of node_id -> node object for fast neighbor lookup.
 * @param {Array} meshTargets
 * @returns {Object} map of target_id/node_id -> node
 */
function meshBuildNodeMap(meshTargets) {
    var map = {};
    for (var i = 0; i < meshTargets.length; i++) {
        var n = meshTargets[i];
        var id = n.target_id || (n.metadata && n.metadata.node_id) || '';
        if (id) map[id] = n;
        // Also index by short forms (mesh_XXXX -> XXXX)
        if (id.indexOf('mesh_') === 0) map[id.slice(5)] = n;
    }
    return map;
}

/**
 * Check if node A lists node B as a neighbor (or vice versa).
 * Uses metadata.neighbors (array of node IDs) or metadata.rssi_map keys.
 * @param {object} a
 * @param {object} b
 * @returns {{ linked: boolean, snrAB: number|undefined, snrBA: number|undefined, hops: number|undefined }}
 */
function meshAreNeighbors(a, b) {
    var result = { linked: false, snrAB: undefined, snrBA: undefined, hops: undefined };
    var metaA = a.metadata || {};
    var metaB = b.metadata || {};

    var idA = a.target_id || metaA.node_id || '';
    var idB = b.target_id || metaB.node_id || '';
    var shortA = idA.indexOf('mesh_') === 0 ? idA.slice(5) : idA;
    var shortB = idB.indexOf('mesh_') === 0 ? idB.slice(5) : idB;

    // Check A's neighbor list for B
    var neighborsA = metaA.neighbors || [];
    var rssiMapA = metaA.rssi_map || {};
    var neighborsB = metaB.neighbors || [];
    var rssiMapB = metaB.rssi_map || {};

    var aHasB = neighborsA.indexOf(idB) >= 0 || neighborsA.indexOf(shortB) >= 0
             || rssiMapA[idB] !== undefined || rssiMapA[shortB] !== undefined;
    var bHasA = neighborsB.indexOf(idA) >= 0 || neighborsB.indexOf(shortA) >= 0
             || rssiMapB[idA] !== undefined || rssiMapB[shortA] !== undefined;

    if (!aHasB && !bHasA) return result;

    result.linked = true;

    // Extract per-link SNR from rssi_map if available
    if (rssiMapA[idB] !== undefined) result.snrAB = rssiMapA[idB];
    else if (rssiMapA[shortB] !== undefined) result.snrAB = rssiMapA[shortB];

    if (rssiMapB[idA] !== undefined) result.snrBA = rssiMapB[idA];
    else if (rssiMapB[shortA] !== undefined) result.snrBA = rssiMapB[shortA];

    // Hop count: use the lower of the two nodes' hop_count values if present
    var hopsA = metaA.hop_count !== undefined ? metaA.hop_count : (a.hop_count !== undefined ? a.hop_count : undefined);
    var hopsB = metaB.hop_count !== undefined ? metaB.hop_count : (b.hop_count !== undefined ? b.hop_count : undefined);
    if (hopsA !== undefined && hopsB !== undefined) {
        result.hops = Math.abs(hopsA - hopsB);
    } else if (hopsA !== undefined || hopsB !== undefined) {
        result.hops = hopsA !== undefined ? hopsA : hopsB;
    }

    return result;
}

/**
 * Get link color based on actual per-link SNR values.
 * @param {number|undefined} snrAB - SNR from A's perspective
 * @param {number|undefined} snrBA - SNR from B's perspective
 * @param {object} a - node A (fallback to node-level SNR)
 * @param {object} b - node B (fallback to node-level SNR)
 * @returns {string} CSS color
 */
function meshGetLinkColorFromSNR(snrAB, snrBA, a, b) {
    // Prefer per-link SNR, fall back to node-level SNR
    var snrVals = [];
    if (snrAB !== undefined) snrVals.push(snrAB);
    if (snrBA !== undefined) snrVals.push(snrBA);
    if (snrVals.length === 0) {
        // Fall back to node-level SNR
        return meshGetLinkColor(a, b);
    }
    var avg = 0;
    for (var i = 0; i < snrVals.length; i++) avg += snrVals[i];
    avg /= snrVals.length;

    if (avg > 5) return MESH_LINK_QUALITY.excellent;
    if (avg > 0) return MESH_LINK_QUALITY.good;
    if (avg > -5) return MESH_LINK_QUALITY.fair;
    return MESH_LINK_QUALITY.poor;
}

// ============================================================
// Draw functions
// ============================================================

/**
 * Draw links between mesh nodes that are actual neighbors.
 * Only draws links when real neighbor data exists (metadata.neighbors or
 * metadata.rssi_map). Lines colored by actual per-link SNR.
 * Hop count labels drawn at link midpoints.
 *
 * @param {CanvasRenderingContext2D} ctx
 * @param {function} worldToScreen
 * @param {Array} meshTargets
 */
function meshDrawLinks(ctx, worldToScreen, meshTargets) {
    if (!meshState.showLinks || !meshTargets || meshTargets.length === 0) return;

    ctx.save();
    ctx.globalAlpha = meshState.opacity;
    ctx.lineWidth = 1.5;
    ctx.setLineDash([4, 6]);

    // Track drawn pairs to avoid duplicates
    var drawn = {};

    for (var i = 0; i < meshTargets.length; i++) {
        for (var j = i + 1; j < meshTargets.length; j++) {
            var a = meshTargets[i];
            var b = meshTargets[j];

            // Only draw if real neighbor data confirms a link
            var link = meshAreNeighbors(a, b);
            if (!link.linked) continue;

            var pairKey = i + ':' + j;
            if (drawn[pairKey]) continue;
            drawn[pairKey] = true;

            ctx.strokeStyle = meshGetLinkColorFromSNR(link.snrAB, link.snrBA, a, b);
            var sa = worldToScreen(a.x, a.y);
            var sb = worldToScreen(b.x, b.y);
            ctx.beginPath();
            ctx.moveTo(sa.x, sa.y);
            ctx.lineTo(sb.x, sb.y);
            ctx.stroke();

            // Draw hop count label at midpoint
            if (link.hops !== undefined) {
                var mx = (sa.x + sb.x) / 2;
                var my = (sa.y + sb.y) / 2;
                ctx.setLineDash([]);
                ctx.globalAlpha = 0.6 * meshState.opacity;
                ctx.fillStyle = MESH_NODE_COLOR;
                ctx.font = '8px "JetBrains Mono", monospace';
                ctx.textAlign = 'center';
                ctx.textBaseline = 'middle';
                ctx.fillText(link.hops + 'h', mx, my - 6);
                ctx.globalAlpha = meshState.opacity;
                ctx.setLineDash([4, 6]);
            }
        }
    }

    ctx.setLineDash([]);
    ctx.restore();
}

/**
 * Draw mesh radio nodes on the tactical map canvas.
 * Green radio icons with node name labels, sized by SNR quality.
 *
 * @param {CanvasRenderingContext2D} ctx
 * @param {function} worldToScreen - (wx, wy) => { x, y }
 * @param {Array} meshTargets - array of mesh_radio targets with
 *   { target_id, x, y, asset_type, metadata: { mesh_protocol, snr }, name }
 * @param {boolean} visible - whether the master layer is visible
 * @param {number} [metersToPixels] - optional conversion for coverage circles
 */
function meshDrawNodes(ctx, worldToScreen, meshTargets, visible, metersToPixels) {
    if (!visible || !meshTargets || meshTargets.length === 0) return;

    // Draw links (real neighbor data only, no fake coverage)
    meshDrawLinks(ctx, worldToScreen, meshTargets);

    // Draw nodes
    if (!meshState.showNodes) return;

    ctx.save();
    ctx.globalAlpha = meshState.opacity;

    for (let i = 0; i < meshTargets.length; i++) {
        const node = meshTargets[i];
        const protocol = (node.metadata && node.metadata.mesh_protocol) || 'meshtastic';
        const icon = meshGetIconForProtocol(protocol);
        const sp = worldToScreen(node.x, node.y);
        const radius = meshGetNodeRadius(node);

        // Outer glow circle
        ctx.fillStyle = MESH_NODE_COLOR;
        ctx.globalAlpha = 0.2 * meshState.opacity;
        ctx.beginPath();
        ctx.arc(sp.x, sp.y, radius + 4, 0, Math.PI * 2);
        ctx.fill();

        // Main circle
        ctx.globalAlpha = 0.4 * meshState.opacity;
        ctx.beginPath();
        ctx.arc(sp.x, sp.y, radius, 0, Math.PI * 2);
        ctx.fill();

        // Inner icon letter
        ctx.globalAlpha = 1.0 * meshState.opacity;
        ctx.fillStyle = MESH_NODE_COLOR;
        ctx.font = 'bold ' + Math.max(8, Math.round(radius * 1.1)) + 'px "JetBrains Mono", monospace';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText(icon, sp.x, sp.y);

        // Node name label (below icon)
        const name = node.name || (node.metadata && node.metadata.short_name) || '';
        if (name) {
            ctx.globalAlpha = 0.7 * meshState.opacity;
            ctx.fillStyle = MESH_NODE_COLOR;
            ctx.font = '9px "JetBrains Mono", monospace';
            ctx.textAlign = 'center';
            ctx.textBaseline = 'top';
            ctx.fillText(name, sp.x, sp.y + radius + 3);
        }
    }

    ctx.restore();
}

// ============================================================
// Exports (CommonJS for Node.js test runner, also global for browser)
// ============================================================

if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
        MESH_PROTOCOL_ICONS,
        MESH_NODE_COLOR,
        MESH_LINK_COLOR,
        MESH_LINK_RANGE,
        MESH_LINK_QUALITY,
        meshDrawNodes,
        meshDrawLinks,
        meshGetIconForProtocol,
        meshShouldDrawLink,
        meshGetLinkColor,
        meshGetLinkColorFromSNR,
        meshGetNodeRadius,
        meshGetNodeCount,
        meshFetchNodes,
        meshStartAutoRefresh,
        meshStopAutoRefresh,
        meshAreNeighbors,
        meshBuildNodeMap,
        meshState,
    };
}
