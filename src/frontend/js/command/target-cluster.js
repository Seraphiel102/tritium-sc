// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * Target clustering — groups nearby targets into clusters for map
 * readability when zoomed out.  When zoomed in, clusters expand into
 * individual targets.
 *
 * Uses a simple grid-based spatial hash for O(n) clustering.  Each
 * cell in the grid becomes a cluster if it contains 2+ targets.
 *
 * Usage:
 *   import { TargetClusterer } from './target-cluster.js';
 *   const clusterer = new TargetClusterer();
 *   const { singles, clusters } = clusterer.cluster(targets, zoom);
 */

/**
 * @typedef {Object} Cluster
 * @property {string} cluster_id - Unique cluster identifier
 * @property {number} lat - Center latitude
 * @property {number} lng - Center longitude
 * @property {number} count - Number of targets in this cluster
 * @property {string} dominant_alliance - Most common alliance in cluster
 * @property {string} dominant_type - Most common asset_type in cluster
 * @property {Array} target_ids - IDs of targets in this cluster
 */

// Zoom thresholds: above this zoom, don't cluster at all
const CLUSTER_ZOOM_MAX = 18;
// Below this zoom, cluster aggressively
const CLUSTER_ZOOM_MIN = 12;
// Minimum targets in a cell to form a cluster
const CLUSTER_MIN_SIZE = 2;

/**
 * Grid cell size in degrees at various zoom levels.
 * Lower zoom = larger cells = more aggressive clustering.
 */
function _cellSizeForZoom(zoom) {
    if (zoom >= CLUSTER_ZOOM_MAX) return 0;  // no clustering
    if (zoom >= 17) return 0.0002;   // ~20m
    if (zoom >= 16) return 0.0005;   // ~50m
    if (zoom >= 15) return 0.001;    // ~100m
    if (zoom >= 14) return 0.002;    // ~200m
    if (zoom >= 13) return 0.005;    // ~500m
    return 0.01;                     // ~1km
}

export class TargetClusterer {
    constructor() {
        this._lastZoom = -1;
        this._lastResult = null;
        this._lastInputHash = '';
    }

    /**
     * Cluster an array of target objects by geographic proximity.
     *
     * @param {Array<Object>} targets - Array of target dicts with lat, lng, target_id
     * @param {number} zoom - Current map zoom level
     * @returns {{ singles: Array<Object>, clusters: Array<Cluster> }}
     */
    cluster(targets, zoom) {
        const cellSize = _cellSizeForZoom(zoom);

        // No clustering at high zoom
        if (cellSize === 0 || !targets || targets.length === 0) {
            return { singles: targets || [], clusters: [] };
        }

        // Grid-based spatial hash
        const grid = new Map();

        for (const t of targets) {
            const lat = t.lat || 0;
            const lng = t.lng || 0;
            if (lat === 0 && lng === 0) continue;

            const cellX = Math.floor(lng / cellSize);
            const cellY = Math.floor(lat / cellSize);
            const key = `${cellX}:${cellY}`;

            if (!grid.has(key)) {
                grid.set(key, []);
            }
            grid.get(key).push(t);
        }

        const singles = [];
        const clusters = [];
        let clusterIdx = 0;

        for (const [key, members] of grid) {
            if (members.length < CLUSTER_MIN_SIZE) {
                singles.push(...members);
                continue;
            }

            // Compute cluster center
            let sumLat = 0, sumLng = 0;
            const allianceCounts = {};
            const typeCounts = {};

            for (const m of members) {
                sumLat += (m.lat || 0);
                sumLng += (m.lng || 0);

                const alliance = m.alliance || 'unknown';
                allianceCounts[alliance] = (allianceCounts[alliance] || 0) + 1;

                const atype = m.asset_type || 'unknown';
                typeCounts[atype] = (typeCounts[atype] || 0) + 1;
            }

            const count = members.length;
            const dominantAlliance = Object.entries(allianceCounts)
                .sort((a, b) => b[1] - a[1])[0][0];
            const dominantType = Object.entries(typeCounts)
                .sort((a, b) => b[1] - a[1])[0][0];

            clusters.push({
                cluster_id: `cluster_${clusterIdx++}`,
                lat: sumLat / count,
                lng: sumLng / count,
                count,
                dominant_alliance: dominantAlliance,
                dominant_type: dominantType,
                target_ids: members.map(m => m.target_id || m.id || ''),
            });
        }

        // Add targets with no position as singles
        for (const t of targets) {
            const lat = t.lat || 0;
            const lng = t.lng || 0;
            if (lat === 0 && lng === 0) {
                singles.push(t);
            }
        }

        return { singles, clusters };
    }
}

/**
 * Create a MapLibre marker DOM element for a cluster.
 * Shows count badge with alliance color.
 */
export function createClusterMarkerElement(cluster) {
    const el = document.createElement('div');
    el.className = 'tritium-cluster-marker';

    const colors = {
        friendly: '#05ffa1',
        hostile: '#ff2a6d',
        neutral: '#00a0ff',
        unknown: '#fcee0a',
    };
    const color = colors[cluster.dominant_alliance] || colors.unknown;

    // Size scales with count
    const size = Math.min(24 + Math.sqrt(cluster.count) * 8, 64);

    el.style.cssText = `
        width: ${size}px;
        height: ${size}px;
        border-radius: 50%;
        background: ${color}22;
        border: 2px solid ${color};
        display: flex;
        align-items: center;
        justify-content: center;
        font-family: 'JetBrains Mono', monospace;
        font-size: ${Math.max(10, size * 0.35)}px;
        font-weight: bold;
        color: ${color};
        cursor: pointer;
        transition: transform 0.2s ease;
        box-shadow: 0 0 ${size * 0.4}px ${color}44;
        pointer-events: auto;
    `;
    el.textContent = cluster.count;

    el.addEventListener('mouseenter', () => {
        el.style.transform = 'scale(1.2)';
    });
    el.addEventListener('mouseleave', () => {
        el.style.transform = 'scale(1)';
    });

    return el;
}
