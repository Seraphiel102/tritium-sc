// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * Tactical Situation Banner — persistent top bar below the menu showing:
 *   - Threat level (GREEN/YELLOW/ORANGE/RED) with color indicator
 *   - Active target count
 *   - Active alerts count
 *   - Amy status
 *
 * Updates live via WebSocket events through the EventBus/TritiumStore.
 */

import { TritiumStore } from './store.js';
import { EventBus } from './events.js';

const THREAT_LEVELS = {
    GREEN:  { color: '#05ffa1', label: 'GREEN',  bg: '#05ffa110' },
    YELLOW: { color: '#fcee0a', label: 'YELLOW', bg: '#fcee0a10' },
    ORANGE: { color: '#ff8800', label: 'ORANGE', bg: '#ff880010' },
    RED:    { color: '#ff2a6d', label: 'RED',    bg: '#ff2a6d10' },
};

/**
 * Create and mount the tactical situation banner into the given container.
 * @param {HTMLElement} container - element to insert the banner into
 * @returns {{ destroy: Function }} cleanup handle
 */
export function createTacticalBanner(container) {
    const banner = document.createElement('div');
    banner.id = 'tactical-banner';
    banner.className = 'tactical-banner';

    banner.innerHTML = `
        <div class="tb-section tb-threat">
            <span class="tb-threat-dot" data-bind="threat-dot"></span>
            <span class="tb-label mono">THREAT</span>
            <span class="tb-threat-level mono" data-bind="threat-level">GREEN</span>
        </div>
        <span class="tb-sep"></span>
        <div class="tb-section">
            <span class="tb-label mono">TARGETS</span>
            <span class="tb-value mono" data-bind="target-count">0</span>
        </div>
        <span class="tb-sep"></span>
        <div class="tb-section">
            <span class="tb-label mono">ALERTS</span>
            <span class="tb-value tb-alert-value mono" data-bind="alert-count">0</span>
        </div>
        <span class="tb-sep"></span>
        <div class="tb-section tb-amy-section">
            <span class="tb-amy-dot" data-bind="amy-dot"></span>
            <span class="tb-label mono">AMY</span>
            <span class="tb-value mono" data-bind="amy-status">IDLE</span>
        </div>
    `;

    container.appendChild(banner);

    // State
    let currentThreatLevel = 'GREEN';
    let alertCount = 0;

    // DOM refs
    const threatDot = banner.querySelector('[data-bind="threat-dot"]');
    const threatLevel = banner.querySelector('[data-bind="threat-level"]');
    const targetCount = banner.querySelector('[data-bind="target-count"]');
    const alertCountEl = banner.querySelector('[data-bind="alert-count"]');
    const amyDot = banner.querySelector('[data-bind="amy-dot"]');
    const amyStatus = banner.querySelector('[data-bind="amy-status"]');

    function updateThreatLevel(level) {
        const key = (level || 'GREEN').toUpperCase();
        const config = THREAT_LEVELS[key] || THREAT_LEVELS.GREEN;
        currentThreatLevel = key;
        threatLevel.textContent = config.label;
        threatLevel.style.color = config.color;
        threatDot.style.background = config.color;
        threatDot.style.boxShadow = `0 0 6px ${config.color}`;
        banner.style.borderBottomColor = `${config.color}33`;

        // Pulse animation on RED
        if (key === 'RED') {
            threatDot.classList.add('tb-pulse');
        } else {
            threatDot.classList.remove('tb-pulse');
        }
    }

    function updateTargetCount() {
        const units = TritiumStore.units;
        let total = 0;
        units.forEach(() => total++);
        targetCount.textContent = total;
    }

    function updateAlertCount() {
        const alerts = TritiumStore.alerts || [];
        const unread = alerts.filter(a => !a.read).length;
        alertCount = unread;
        alertCountEl.textContent = unread;
        alertCountEl.classList.toggle('tb-alert-active', unread > 0);
    }

    function updateAmyStatus() {
        const state = TritiumStore.amy?.state || 'idle';
        amyStatus.textContent = state.toUpperCase();

        const amyColors = {
            idle: '#666',
            thinking: '#fcee0a',
            speaking: '#05ffa1',
            listening: '#00f0ff',
            commanding: '#ff8800',
            observing: '#00a0ff',
        };
        const color = amyColors[state] || '#666';
        amyDot.style.background = color;
        amyDot.style.boxShadow = `0 0 4px ${color}`;
    }

    function deriveThreatLevel() {
        // Derive threat level from hostile count and alert state
        const units = TritiumStore.units;
        let hostileCount = 0;
        units.forEach(u => {
            if (u.alliance === 'hostile') hostileCount++;
        });

        const alerts = TritiumStore.alerts || [];
        const recentAlerts = alerts.filter(a => {
            const age = Date.now() - (a.time || 0);
            return age < 300000; // last 5 minutes
        }).length;

        let level = 'GREEN';
        if (hostileCount > 0 || recentAlerts > 5) level = 'YELLOW';
        if (hostileCount > 3 || recentAlerts > 10) level = 'ORANGE';
        if (hostileCount > 8 || recentAlerts > 20) level = 'RED';

        // Game phase override
        const phase = TritiumStore.game?.phase;
        if (phase === 'active') {
            level = hostileCount > 5 ? 'RED' : hostileCount > 0 ? 'ORANGE' : 'YELLOW';
        }

        updateThreatLevel(level);
    }

    // Subscribe to store changes
    const unsubs = [];
    unsubs.push(TritiumStore.on('units', () => {
        updateTargetCount();
        deriveThreatLevel();
    }));
    unsubs.push(TritiumStore.on('alerts', () => {
        updateAlertCount();
        deriveThreatLevel();
    }));
    unsubs.push(TritiumStore.on('amy.state', () => {
        updateAmyStatus();
    }));
    unsubs.push(TritiumStore.on('game.phase', () => {
        deriveThreatLevel();
    }));

    // Listen for explicit escalation events
    const onEscalation = (data) => {
        if (data && data.level) {
            updateThreatLevel(data.level);
        }
    };
    EventBus.on('escalation:change', onEscalation);

    // Initial render
    updateThreatLevel('GREEN');
    updateTargetCount();
    updateAlertCount();
    updateAmyStatus();

    return {
        destroy() {
            for (const unsub of unsubs) unsub();
            EventBus.off('escalation:change', onEscalation);
            banner.remove();
        },
    };
}
