// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// LPR (License Plate Recognition) Panel — recent detections, watchlist
// management, plate search, and watchlist hit alerts.
// Backend API: /api/lpr (detections, watchlist, search, stats)

import { EventBus } from '../events.js';
import { _esc } from '../panel-utils.js';


const ALERT_COLORS = {
    stolen: '#ff2a6d',
    wanted: '#ff2a6d',
    amber_alert: '#fcee0a',
    bolo: '#ff8c00',
    custom: '#00f0ff',
    none: '#888',
};

export const LprPanelDef = {
    id: 'lpr',
    title: 'LPR / PLATE READER',
    defaultPosition: { x: 340, y: 60 },
    defaultSize: { w: 380, h: 460 },

    create(panel) {
        const el = document.createElement('div');
        el.className = 'lpr-panel-inner';
        el.innerHTML = `
            <div class="lpr-toolbar" style="display:flex;gap:4px;padding:4px;align-items:center">
                <button class="panel-action-btn panel-action-btn-primary" data-action="refresh" title="Refresh">REFRESH</button>
                <span class="lpr-stats" data-bind="stats" style="font-size:0.42rem;color:#888;flex:1;text-align:right"></span>
            </div>
            <div class="lpr-tab-bar" style="display:flex;gap:2px;margin:2px 4px">
                <button class="panel-action-btn panel-action-btn-primary lpr-tab" data-tab="detections" style="flex:1;font-size:0.43rem">DETECTIONS</button>
                <button class="panel-action-btn lpr-tab" data-tab="watchlist" style="flex:1;font-size:0.43rem">WATCHLIST</button>
                <button class="panel-action-btn lpr-tab" data-tab="search" style="flex:1;font-size:0.43rem">SEARCH</button>
            </div>
            <div class="lpr-search-bar" data-bind="search-bar" style="display:none;padding:4px">
                <input type="text" class="panel-input" data-bind="search-input" placeholder="Search plate (partial OK)..."
                    style="width:100%;background:#12121a;border:1px solid #333;color:#ccc;padding:4px 8px;font-family:monospace;font-size:0.45rem">
            </div>
            <div class="lpr-add-form" data-bind="add-form" style="display:none;padding:4px;border-bottom:1px solid #222">
                <div style="display:flex;gap:4px;margin-bottom:4px">
                    <input type="text" class="panel-input" data-bind="add-plate" placeholder="PLATE TEXT"
                        style="flex:2;background:#12121a;border:1px solid #333;color:#05ffa1;padding:4px 6px;font-family:monospace;font-size:0.45rem;text-transform:uppercase">
                    <select data-bind="add-type" style="flex:1;background:#12121a;border:1px solid #333;color:#ccc;padding:4px;font-size:0.42rem">
                        <option value="bolo">BOLO</option>
                        <option value="stolen">STOLEN</option>
                        <option value="wanted">WANTED</option>
                        <option value="amber_alert">AMBER</option>
                        <option value="custom">CUSTOM</option>
                    </select>
                </div>
                <div style="display:flex;gap:4px">
                    <input type="text" class="panel-input" data-bind="add-desc" placeholder="Description..."
                        style="flex:1;background:#12121a;border:1px solid #333;color:#ccc;padding:4px 6px;font-size:0.42rem">
                    <button class="panel-action-btn panel-action-btn-primary" data-action="add-plate" style="font-size:0.42rem">+ ADD</button>
                </div>
            </div>
            <ul class="panel-list lpr-list" data-bind="list" role="listbox" aria-label="LPR data">
                <li class="panel-empty">Loading...</li>
            </ul>
        `;
        return el;
    },

    init(panel) {
        const el = panel.contentEl;
        let activeTab = 'detections';
        let pollTimer = null;

        // Tab switching
        el.querySelectorAll('.lpr-tab').forEach(btn => {
            btn.addEventListener('click', () => {
                el.querySelectorAll('.lpr-tab').forEach(b =>
                    b.classList.remove('panel-action-btn-primary')
                );
                btn.classList.add('panel-action-btn-primary');
                activeTab = btn.dataset.tab;

                // Show/hide search bar and add form
                const searchBar = el.querySelector('[data-bind="search-bar"]');
                const addForm = el.querySelector('[data-bind="add-form"]');
                searchBar.style.display = activeTab === 'search' ? 'block' : 'none';
                addForm.style.display = activeTab === 'watchlist' ? 'block' : 'none';

                refresh();
            });
        });

        // Toolbar
        el.querySelector('[data-action="refresh"]').addEventListener('click', refresh);

        // Search input
        let searchDebounce = null;
        const searchInput = el.querySelector('[data-bind="search-input"]');
        searchInput.addEventListener('input', () => {
            clearTimeout(searchDebounce);
            searchDebounce = setTimeout(() => searchPlates(searchInput.value), 300);
        });

        // Add plate button
        el.querySelector('[data-action="add-plate"]').addEventListener('click', addPlate);

        async function refresh() {
            try {
                if (activeTab === 'detections') await loadDetections();
                else if (activeTab === 'watchlist') await loadWatchlist();
                else if (activeTab === 'search') await searchPlates(searchInput.value);
                await loadStats();
            } catch (err) {
                console.warn('[lpr] refresh error:', err);
            }
        }

        async function loadStats() {
            try {
                const res = await fetch('/api/lpr/stats');
                if (!res.ok) return;
                const data = await res.json();
                const statsEl = el.querySelector('[data-bind="stats"]');
                if (statsEl) {
                    statsEl.textContent = `${data.total_detections || 0} reads | `
                        + `${data.unique_plates || 0} plates | `
                        + `${data.watchlist_hits || 0} hits`;
                    if (data.watchlist_hits > 0) {
                        statsEl.style.color = '#ff2a6d';
                    } else {
                        statsEl.style.color = '#888';
                    }
                }
            } catch (_) { /* ignore */ }
        }

        async function loadDetections() {
            const list = el.querySelector('[data-bind="list"]');
            try {
                const res = await fetch('/api/lpr/detections?count=50');
                if (!res.ok) { list.innerHTML = '<li class="panel-empty">API unavailable</li>'; return; }
                const data = await res.json();
                if (!data.length) {
                    list.innerHTML = '<li class="panel-empty">No plate detections yet</li>';
                    return;
                }
                list.innerHTML = data.slice().reverse().map(d => {
                    const ts = new Date(d.timestamp * 1000).toLocaleTimeString();
                    const conf = Math.round((d.confidence || 0) * 100);
                    const hitColor = d.watchlist_hit ? ALERT_COLORS[d.alert_type] || '#ff2a6d' : '#333';
                    const hitBadge = d.watchlist_hit
                        ? `<span style="color:${_esc(hitColor)};font-weight:bold;font-size:0.42rem;margin-left:4px">[${_esc(d.alert_type.toUpperCase())}]</span>`
                        : '';
                    const vehicle = d.vehicle_type
                        ? `<span style="color:#888;font-size:0.4rem"> ${_esc(d.vehicle_color)} ${_esc(d.vehicle_type)}</span>`
                        : '';
                    return `<li class="panel-list-item" style="border-left:3px solid ${_esc(hitColor)};padding-left:6px;cursor:pointer" data-plate="${_esc(d.plate_text)}">
                        <span style="color:#05ffa1;font-weight:bold;font-family:monospace;font-size:0.5rem;letter-spacing:1px">${_esc(d.plate_text)}</span>
                        ${hitBadge}${vehicle}
                        <span style="color:#888;font-size:0.38rem;margin-left:4px">${conf}%</span>
                        <span style="color:#555;font-size:0.38rem;float:right">${_esc(d.camera_id || '?')} ${ts}</span>
                    </li>`;
                }).join('');
            } catch (err) {
                list.innerHTML = '<li class="panel-empty">Error loading detections</li>';
            }
        }

        async function loadWatchlist() {
            const list = el.querySelector('[data-bind="list"]');
            try {
                const res = await fetch('/api/lpr/watchlist');
                if (!res.ok) { list.innerHTML = '<li class="panel-empty">API unavailable</li>'; return; }
                const data = await res.json();
                if (!data.length) {
                    list.innerHTML = '<li class="panel-empty">Watchlist empty</li>';
                    return;
                }
                list.innerHTML = data.map(e => {
                    const color = ALERT_COLORS[e.alert_type] || '#00f0ff';
                    const added = new Date(e.added_at * 1000).toLocaleDateString();
                    const expires = e.expires_at
                        ? `Exp: ${new Date(e.expires_at * 1000).toLocaleDateString()}`
                        : 'No expiry';
                    return `<li class="panel-list-item" style="border-left:3px solid ${_esc(color)};padding-left:6px">
                        <span style="color:#05ffa1;font-weight:bold;font-family:monospace;font-size:0.48rem;letter-spacing:1px">${_esc(e.plate_text)}</span>
                        <span style="color:${_esc(color)};font-size:0.42rem;margin-left:6px">[${_esc(e.alert_type.toUpperCase())}]</span>
                        <button class="panel-action-btn lpr-remove-btn" data-remove-plate="${_esc(e.plate_normalized)}"
                            style="float:right;font-size:0.38rem;padding:1px 4px;color:#ff2a6d;border-color:#ff2a6d" title="Remove from watchlist">X</button>
                        <div style="color:#888;font-size:0.38rem;margin-top:2px">${_esc(e.description || '—')} | Added: ${added} | ${expires}</div>
                    </li>`;
                }).join('');

                // Wire remove buttons
                list.querySelectorAll('.lpr-remove-btn').forEach(btn => {
                    btn.addEventListener('click', async (ev) => {
                        ev.stopPropagation();
                        const plate = btn.dataset.removePlate;
                        try {
                            await fetch(`/api/lpr/watchlist/${encodeURIComponent(plate)}`, { method: 'DELETE' });
                            refresh();
                        } catch (err) {
                            console.warn('[lpr] remove error:', err);
                        }
                    });
                });
            } catch (err) {
                list.innerHTML = '<li class="panel-empty">Error loading watchlist</li>';
            }
        }

        async function searchPlates(query) {
            const list = el.querySelector('[data-bind="list"]');
            if (!query || query.length < 2) {
                list.innerHTML = '<li class="panel-empty">Type at least 2 characters to search</li>';
                return;
            }
            try {
                const res = await fetch(`/api/lpr/search?q=${encodeURIComponent(query)}&limit=30`);
                if (!res.ok) { list.innerHTML = '<li class="panel-empty">API unavailable</li>'; return; }
                const data = await res.json();
                if (!data.length) {
                    list.innerHTML = '<li class="panel-empty">No plates matching query</li>';
                    return;
                }
                list.innerHTML = data.map(d => {
                    const ts = new Date(d.timestamp * 1000).toLocaleTimeString();
                    const hitColor = d.watchlist_hit ? ALERT_COLORS[d.alert_type] || '#ff2a6d' : '#333';
                    const hitBadge = d.watchlist_hit
                        ? `<span style="color:${_esc(hitColor)};font-weight:bold;font-size:0.42rem">[${_esc(d.alert_type.toUpperCase())}]</span>`
                        : '';
                    return `<li class="panel-list-item" style="border-left:3px solid ${_esc(hitColor)};padding-left:6px">
                        <span style="color:#05ffa1;font-weight:bold;font-family:monospace;font-size:0.5rem;letter-spacing:1px">${_esc(d.plate_text)}</span>
                        ${hitBadge}
                        <span style="color:#555;font-size:0.38rem;float:right">${_esc(d.camera_id || '?')} ${ts}</span>
                    </li>`;
                }).join('');
            } catch (err) {
                list.innerHTML = '<li class="panel-empty">Search error</li>';
            }
        }

        async function addPlate() {
            const plateInput = el.querySelector('[data-bind="add-plate"]');
            const typeSelect = el.querySelector('[data-bind="add-type"]');
            const descInput = el.querySelector('[data-bind="add-desc"]');
            const plateText = plateInput.value.trim();

            if (!plateText) return;

            try {
                const res = await fetch('/api/lpr/watchlist', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        plate_text: plateText,
                        alert_type: typeSelect.value,
                        description: descInput.value.trim(),
                        notify: true,
                    }),
                });
                if (res.ok) {
                    plateInput.value = '';
                    descInput.value = '';
                    refresh();
                }
            } catch (err) {
                console.warn('[lpr] add plate error:', err);
            }
        }

        // WebSocket events for real-time LPR updates
        EventBus.on('lpr:detection', () => {
            if (activeTab === 'detections') refresh();
        });
        EventBus.on('lpr:watchlist_hit', () => {
            refresh();
        });

        // Initial load
        refresh();

        // Poll every 5 seconds
        pollTimer = setInterval(refresh, 5000);

        panel._lprCleanup = () => {
            if (pollTimer) clearInterval(pollTimer);
        };
    },

    destroy(panel) {
        if (panel._lprCleanup) panel._lprCleanup();
    },
};
