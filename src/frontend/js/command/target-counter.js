// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// Target Counter Widget — real-time target counts in the header bar
//
// Updates live via TritiumStore subscription. Shows:
//   total targets | friendly | hostile | unknown
//
// Usage:
//   import { initTargetCounter } from './target-counter.js';
//   initTargetCounter();

import { TritiumStore } from './store.js';

let _totalEl = null;
let _friendlyEl = null;
let _hostileEl = null;
let _unknownEl = null;
let _updateTimer = null;

/**
 * Initialize the target counter widget.
 * Subscribes to store unit changes and updates header stats.
 */
export function initTargetCounter() {
    _totalEl = document.querySelector('[data-target-stat="total"]');
    _friendlyEl = document.querySelector('[data-target-stat="friendly"]');
    _hostileEl = document.querySelector('[data-target-stat="hostile"]');
    _unknownEl = document.querySelector('[data-target-stat="unknown"]');

    if (!_totalEl) return;

    // Subscribe to unit changes
    TritiumStore.on('units', _scheduleUpdate);

    // Initial count
    _updateCounts();
}

/**
 * Debounce updates to avoid excessive DOM writes during batch telemetry.
 */
function _scheduleUpdate() {
    if (_updateTimer) return;
    _updateTimer = requestAnimationFrame(() => {
        _updateTimer = null;
        _updateCounts();
    });
}

/**
 * Count targets from the TritiumStore and update DOM elements.
 */
function _updateCounts() {
    const units = TritiumStore.units;
    if (!units) {
        _setCount(_totalEl, 0);
        _setChip(_friendlyEl, 0);
        _setChip(_hostileEl, 0);
        _setChip(_unknownEl, 0);
        return;
    }

    let total = 0;
    let friendly = 0;
    let hostile = 0;
    let unknown = 0;

    for (const [, unit] of units) {
        // Skip dead/eliminated units
        if (unit.status === 'eliminated' || unit.status === 'destroyed' || unit.status === 'despawned') continue;
        total++;
        const alliance = (unit.alliance || 'unknown').toLowerCase();
        if (alliance === 'friendly') friendly++;
        else if (alliance === 'hostile') hostile++;
        else unknown++;
    }

    _setCount(_totalEl, total);
    _setChip(_friendlyEl, friendly);
    _setChip(_hostileEl, hostile);
    _setChip(_unknownEl, unknown);
}

function _setCount(el, value) {
    if (el && el.textContent !== String(value)) {
        el.textContent = value;
    }
}

function _setChip(el, value) {
    if (!el) return;
    const str = String(value);
    if (el.textContent !== str) el.textContent = str;
    el.setAttribute('data-count', str);
    // Show/hide based on whether count > 0
    el.style.display = value > 0 ? '' : 'none';
}

/**
 * Get current target counts (for external consumers).
 * @returns {{ total: number, friendly: number, hostile: number, unknown: number }}
 */
export function getTargetCounts() {
    const units = TritiumStore.units;
    if (!units) return { total: 0, friendly: 0, hostile: 0, unknown: 0 };

    let total = 0, friendly = 0, hostile = 0, unknown = 0;
    for (const [, unit] of units) {
        if (unit.status === 'eliminated' || unit.status === 'destroyed' || unit.status === 'despawned') continue;
        total++;
        const alliance = (unit.alliance || 'unknown').toLowerCase();
        if (alliance === 'friendly') friendly++;
        else if (alliance === 'hostile') hostile++;
        else unknown++;
    }
    return { total, friendly, hostile, unknown };
}
