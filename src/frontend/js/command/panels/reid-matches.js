// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// ReID Matches Panel — cross-camera person re-identification with
// similarity scores, camera sources, timestamps, and dossier links.
// Backend API: /api/reid (matches, stats)

import { EventBus } from '../events.js';
import { _esc } from '../panel-utils.js';


function simColor(sim) {
    if (sim >= 0.95) return '#05ffa1';
    if (sim >= 0.85) return '#00f0ff';
    if (sim >= 0.75) return '#fcee0a';
    return '#888';
}

function simLabel(sim) {
    if (sim >= 0.95) return 'CERTAIN';
    if (sim >= 0.85) return 'HIGH';
    if (sim >= 0.75) return 'LIKELY';
    return 'LOW';
}

export const ReIDMatchesPanelDef = {
    id: 'reid-matches',
    title: 'REID MATCHES',
    defaultPosition: { x: 360, y: 80 },
    defaultSize: { w: 360, h: 440 },

    create(panel) {
        const el = document.createElement('div');
        el.className = 'reid-panel-inner';
        el.innerHTML = `
            <div class="reid-toolbar" style="display:flex;gap:4px;padding:4px;align-items:center">
                <button class="panel-action-btn panel-action-btn-primary" data-action="refresh" title="Refresh">REFRESH</button>
                <span class="reid-stats" data-bind="stats" style="font-size:0.42rem;color:#888;flex:1;text-align:right"></span>
            </div>
            <div class="reid-filter" style="padding:2px 4px">
                <select data-bind="camera-filter" style="background:#12121a;border:1px solid #333;color:#ccc;padding:3px;font-size:0.42rem;width:100%">
                    <option value="">All cameras</option>
                </select>
            </div>
            <ul class="panel-list reid-list" data-bind="list" role="listbox" aria-label="ReID matches">
                <li class="panel-empty">Loading...</li>
            </ul>
        `;
        return el;
    },

    init(panel) {
        const el = panel.contentEl;
        let pollTimer = null;

        const cameraFilter = el.querySelector('[data-bind="camera-filter"]');
        cameraFilter.addEventListener('change', refresh);

        el.querySelector('[data-action="refresh"]').addEventListener('click', refresh);

        async function refresh() {
            try {
                await loadMatches();
                await loadStats();
            } catch (err) {
                console.warn('[reid] refresh error:', err);
            }
        }

        async function loadStats() {
            try {
                const res = await fetch('/api/reid/stats');
                if (!res.ok) return;
                const data = await res.json();
                const statsEl = el.querySelector('[data-bind="stats"]');
                if (statsEl) {
                    statsEl.textContent = `${data.total_entries || 0} embeddings | `
                        + `${data.total_matches || 0} matches | `
                        + `${(data.cameras || []).length} cams`;
                }
                // Populate camera filter
                const cameras = data.cameras || [];
                const current = cameraFilter.value;
                const options = ['<option value="">All cameras</option>'];
                cameras.forEach(cam => {
                    options.push(`<option value="${_esc(cam)}"${cam === current ? ' selected' : ''}>${_esc(cam)}</option>`);
                });
                cameraFilter.innerHTML = options.join('');
            } catch (_) { /* ignore */ }
        }

        async function loadMatches() {
            const list = el.querySelector('[data-bind="list"]');
            const camId = cameraFilter.value;
            let url = '/api/reid/matches?count=40';
            if (camId) url += `&camera_id=${encodeURIComponent(camId)}`;

            try {
                const res = await fetch(url);
                if (!res.ok) { list.innerHTML = '<li class="panel-empty">API unavailable</li>'; return; }
                const data = await res.json();
                if (!data.length) {
                    list.innerHTML = '<li class="panel-empty">No cross-camera matches</li>';
                    return;
                }
                list.innerHTML = data.map(m => {
                    const color = simColor(m.similarity);
                    const label = simLabel(m.similarity);
                    const simPct = Math.round(m.similarity * 100);
                    const tsA = new Date(m.timestamp_a * 1000).toLocaleTimeString();
                    const tsB = new Date(m.timestamp_b * 1000).toLocaleTimeString();
                    const barWidth = Math.round(m.similarity * 100);
                    const dossierLink = m.dossier_id
                        ? `<button class="panel-action-btn reid-dossier-btn" data-dossier="${_esc(m.dossier_id)}"
                            style="font-size:0.36rem;padding:1px 4px;color:#00f0ff;border-color:#00f0ff;float:right" title="View dossier">DOSSIER</button>`
                        : '';

                    return `<li class="panel-list-item" style="border-left:3px solid ${color};padding-left:6px;cursor:pointer" data-target-a="${_esc(m.target_a)}" data-target-b="${_esc(m.target_b)}">
                        <div style="display:flex;justify-content:space-between;align-items:center">
                            <span style="color:#ccc;font-size:0.44rem">${_esc(m.class_name.toUpperCase())}</span>
                            <span style="color:${color};font-weight:bold;font-size:0.44rem">${simPct}% ${label}</span>
                            ${dossierLink}
                        </div>
                        <div style="margin:2px 0;height:4px;background:#1a1a2e;border-radius:2px;overflow:hidden">
                            <div style="width:${barWidth}%;height:100%;background:${color};transition:width 0.3s"></div>
                        </div>
                        <div style="display:flex;justify-content:space-between;font-size:0.38rem;color:#888">
                            <span><span style="color:#00f0ff">${_esc(m.camera_a || '?')}</span> ${_esc(m.target_a)}</span>
                            <span style="color:#555">${tsA}</span>
                        </div>
                        <div style="display:flex;justify-content:space-between;font-size:0.38rem;color:#888">
                            <span><span style="color:#ff2a6d">${_esc(m.camera_b || '?')}</span> ${_esc(m.target_b)}</span>
                            <span style="color:#555">${tsB}</span>
                        </div>
                    </li>`;
                }).join('');

                // Wire dossier buttons
                list.querySelectorAll('.reid-dossier-btn').forEach(btn => {
                    btn.addEventListener('click', (ev) => {
                        ev.stopPropagation();
                        const dossierId = btn.dataset.dossier;
                        EventBus.emit('panel:request-open', { id: 'dossiers' });
                        EventBus.emit('dossier:view', { id: dossierId });
                    });
                });

                // Wire row clicks to open unit inspector
                list.querySelectorAll('.panel-list-item[data-target-a]').forEach(item => {
                    item.addEventListener('click', () => {
                        const targetA = item.dataset.targetA;
                        EventBus.emit('panel:request-open', { id: 'unit-inspector' });
                        EventBus.emit('target:inspect', { id: targetA });
                    });
                });
            } catch (err) {
                list.innerHTML = '<li class="panel-empty">Error loading matches</li>';
            }
        }

        // WebSocket events
        EventBus.on('reid:match', () => refresh());

        // Initial load
        refresh();

        // Poll every 8 seconds
        pollTimer = setInterval(refresh, 8000);

        panel._reidCleanup = () => {
            if (pollTimer) clearInterval(pollTimer);
        };
    },

    destroy(panel) {
        if (panel._reidCleanup) panel._reidCleanup();
    },
};
