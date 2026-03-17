// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// MESHTASTIC — Single tabbed panel for the Meshtastic LoRa Mesh addon.
// Tabs: OVERVIEW | NODES | CHAT | CONFIG
// Auto-connects to /dev/ttyACM0 on open.

import { EventBus } from '/static/js/command/events.js';
import { _esc } from '/static/js/command/panel-utils.js';

const API = '/api/addons/meshtastic';
const REFRESH_MS = 5000;
const MSG_CHAR_LIMIT = 228;

// ─── Tab definitions ────────────────────────────────────────────────
const TABS = [
    { id: 'overview', label: 'OVERVIEW' },
    { id: 'nodes',    label: 'NODES' },
    { id: 'chat',     label: 'CHAT' },
    { id: 'config',   label: 'CONFIG' },
];

// ─── Column defs for node table ─────────────────────────────────────
const NODE_COLS = [
    { key: 'short_name', label: 'NAME',    width: '80px' },
    { key: 'long_name',  label: 'LONG NAME', width: '140px' },
    { key: 'hw_model',   label: 'HW',      width: '90px' },
    { key: 'snr',        label: 'SNR',     width: '50px',  align: 'right' },
    { key: 'battery',    label: 'BAT',     width: '50px',  align: 'right' },
    { key: 'last_heard', label: 'LAST',    width: '60px',  align: 'right' },
    { key: 'hopsAway',   label: 'HOPS',    width: '40px',  align: 'right' },
];

export const MeshtasticPanelDef = {
    id: 'meshtastic',
    title: 'MESHTASTIC',
    defaultPosition: { x: 60, y: 80 },
    defaultSize: { w: 560, h: 620 },

    create() {
        const el = document.createElement('div');
        el.className = 'msh-panel';
        el.style.cssText = 'display:flex;flex-direction:column;height:100%;font-family:var(--font-mono,"JetBrains Mono",monospace);';

        // Tab bar
        const tabHtml = TABS.map((t, i) =>
            `<button class="msh-tab${i === 0 ? ' msh-tab-active' : ''}" data-tab="${t.id}">${t.label}</button>`
        ).join('');

        // Connection bar (always visible)
        el.innerHTML = `
            <div class="msh-conn-bar">
                <span class="msh-dot" data-bind="dot"></span>
                <span class="msh-conn-label" data-bind="conn-label">DISCONNECTED</span>
                <span style="flex:1"></span>
                <span class="msh-conn-info mono" data-bind="conn-info"></span>
                <button class="msh-btn msh-btn-connect" data-action="connect">CONNECT</button>
                <button class="msh-btn msh-btn-disconnect" data-action="disconnect" style="display:none">DISCONNECT</button>
            </div>
            <div class="msh-tabs">${tabHtml}</div>
            <div class="msh-body" data-bind="body"></div>
        `;

        return el;
    },

    mount(bodyEl, panel) {
        const dot = bodyEl.querySelector('[data-bind="dot"]');
        const connLabel = bodyEl.querySelector('[data-bind="conn-label"]');
        const connInfo = bodyEl.querySelector('[data-bind="conn-info"]');
        const connectBtn = bodyEl.querySelector('[data-action="connect"]');
        const disconnectBtn = bodyEl.querySelector('[data-action="disconnect"]');
        const tabContainer = bodyEl.querySelector('.msh-tabs');
        const body = bodyEl.querySelector('[data-bind="body"]');

        let activeTab = 'overview';
        let connected = false;
        let status = {};
        let nodes = [];
        let messages = [];
        let deviceInfo = {};
        let nodeSortKey = 'last_heard';
        let nodeSortDir = -1;

        // ── Styles (injected once) ──────────────────────────────
        _injectStyles();

        // ── Tab switching ───────────────────────────────────────
        tabContainer.addEventListener('click', (e) => {
            const btn = e.target.closest('.msh-tab');
            if (!btn) return;
            activeTab = btn.dataset.tab;
            tabContainer.querySelectorAll('.msh-tab').forEach(t => t.classList.toggle('msh-tab-active', t.dataset.tab === activeTab));
            renderBody();
        });

        // ── Connect ─────────────────────────────────────────────
        connectBtn.addEventListener('click', async () => {
            connectBtn.disabled = true;
            connectBtn.textContent = 'CONNECTING...';
            try {
                const r = await fetch(API + '/connect', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ transport: 'serial', timeout: 60 }),
                });
                if (r.ok) {
                    const d = await r.json();
                    updateConnection(d);
                }
            } catch (_) {}
            connectBtn.disabled = false;
            connectBtn.textContent = 'CONNECT';
        });

        disconnectBtn.addEventListener('click', async () => {
            try { await fetch(API + '/disconnect', { method: 'POST' }); } catch (_) {}
            updateConnection({ connected: false, transport: 'none', port: '', device: {} });
        });

        // ── Connection state ────────────────────────────────────
        function updateConnection(d) {
            if (!d) return;
            connected = d.connected || false;
            status = d;
            dot.className = connected ? 'msh-dot msh-dot-on' : 'msh-dot';
            connLabel.textContent = connected ? 'CONNECTED' : 'DISCONNECTED';
            connLabel.style.color = connected ? '#05ffa1' : '#888';
            const dev = d.device || {};
            connInfo.textContent = connected
                ? `${_esc(dev.long_name || dev.hw_model || '')} via ${_esc(d.transport || '')} ${_esc(d.port || '')}`
                : '';
            connectBtn.style.display = connected ? 'none' : '';
            disconnectBtn.style.display = connected ? '' : 'none';
        }

        // ── Data fetching ───────────────────────────────────────
        async function fetchAll() {
            try {
                const [sRes, nRes] = await Promise.all([
                    fetch(API + '/status').then(r => r.ok ? r.json() : null),
                    fetch(API + '/nodes').then(r => r.ok ? r.json() : null),
                ]);
                if (sRes) updateConnection(sRes);
                if (nRes) { nodes = nRes.nodes || []; }
                renderBody();
            } catch (_) {}
        }

        async function fetchMessages() {
            try {
                const r = await fetch(API + '/messages?limit=100');
                if (r.ok) {
                    const d = await r.json();
                    messages = d.messages || [];
                }
            } catch (_) {}
        }

        async function fetchDeviceInfo() {
            try {
                const r = await fetch(API + '/device/info');
                if (r.ok) deviceInfo = await r.json();
            } catch (_) {}
        }

        // ── Render active tab ───────────────────────────────────
        function renderBody() {
            if (!body) return;
            switch (activeTab) {
                case 'overview': renderOverview(); break;
                case 'nodes':    renderNodes(); break;
                case 'chat':     renderChat(); break;
                case 'config':   renderConfig(); break;
            }
        }

        // ─── OVERVIEW TAB ───────────────────────────────────────
        function renderOverview() {
            const withGps = nodes.filter(n => n.lat != null && (n.lat !== 0 || n.lng !== 0)).length;
            const batts = nodes.map(n => n.battery).filter(b => b != null && b > 0);
            const avgBat = batts.length ? Math.round(batts.reduce((a, b) => a + b, 0) / batts.length) : null;
            const utils = nodes.map(n => n.channel_util).filter(u => u != null);
            const avgUtil = utils.length ? (utils.reduce((a, b) => a + b, 0) / utils.length).toFixed(1) : null;

            const now = Math.floor(Date.now() / 1000);
            const recent = [...nodes].filter(n => n.last_heard).sort((a, b) => b.last_heard - a.last_heard).slice(0, 8);

            body.innerHTML = `
                <div class="msh-stats">
                    <div class="msh-stat"><div class="msh-stat-val" style="color:#00f0ff">${nodes.length}</div><div class="msh-stat-lbl">NODES</div></div>
                    <div class="msh-stat"><div class="msh-stat-val" style="color:#05ffa1">${withGps}</div><div class="msh-stat-lbl">WITH GPS</div></div>
                    <div class="msh-stat"><div class="msh-stat-val" style="color:#fcee0a">${avgBat != null ? avgBat + '%' : '--'}</div><div class="msh-stat-lbl">AVG BATTERY</div></div>
                    <div class="msh-stat"><div class="msh-stat-val" style="color:#ff2a6d">${avgUtil != null ? avgUtil + '%' : '--'}</div><div class="msh-stat-lbl">CHANNEL UTIL</div></div>
                </div>
                <div class="msh-section-label">RECENTLY HEARD</div>
                <div class="msh-recent">
                    ${recent.length === 0 ? '<div class="msh-empty">No nodes heard yet. Connect a radio.</div>' :
                    recent.map(n => {
                        const age = _age(now - (n.last_heard || 0));
                        const bat = n.battery != null ? Math.round(n.battery) + '%' : '';
                        return `<div class="msh-recent-row">
                            <span class="msh-recent-name">${_esc(n.short_name || n.long_name || n.node_id || '?')}</span>
                            <span class="msh-recent-hw">${_esc(n.hw_model || '')}</span>
                            <span class="msh-recent-bat">${bat}</span>
                            <span class="msh-recent-age">${age}</span>
                        </div>`;
                    }).join('')}
                </div>
            `;
        }

        // ─── NODES TAB ──────────────────────────────────────────
        function renderNodes() {
            const sorted = [...nodes].sort((a, b) => {
                let va = a[nodeSortKey], vb = b[nodeSortKey];
                if (typeof va === 'string') return (va || '').localeCompare(vb || '') * nodeSortDir;
                if (va == null) va = -Infinity;
                if (vb == null) vb = -Infinity;
                return (va - vb) * nodeSortDir;
            });

            const now = Math.floor(Date.now() / 1000);
            const headerCells = NODE_COLS.map(c =>
                `<th class="msh-th" data-sort="${c.key}" style="width:${c.width};text-align:${c.align || 'left'}">${c.label}${nodeSortKey === c.key ? (nodeSortDir < 0 ? ' v' : ' ^') : ''}</th>`
            ).join('');

            const rows = sorted.map(n => {
                const age = _age(now - (n.last_heard || 0));
                const bat = n.battery != null ? Math.round(n.battery) + '%' : '';
                const snr = n.snr != null ? n.snr.toFixed(1) : '';
                const hops = n.hopsAway != null ? n.hopsAway : '';
                return `<tr class="msh-tr">
                    <td class="msh-td">${_esc(n.short_name || '')}</td>
                    <td class="msh-td">${_esc(n.long_name || '')}</td>
                    <td class="msh-td">${_esc(n.hw_model || '')}</td>
                    <td class="msh-td" style="text-align:right">${snr}</td>
                    <td class="msh-td" style="text-align:right">${bat}</td>
                    <td class="msh-td" style="text-align:right">${age}</td>
                    <td class="msh-td" style="text-align:right">${hops}</td>
                </tr>`;
            }).join('');

            body.innerHTML = `
                <div class="msh-node-count">${nodes.length} node${nodes.length !== 1 ? 's' : ''}</div>
                <div style="flex:1;overflow:auto;min-height:0;">
                    <table class="msh-table"><thead><tr>${headerCells}</tr></thead><tbody>${rows || '<tr><td colspan="7" class="msh-empty" style="text-align:center;padding:30px">No nodes</td></tr>'}</tbody></table>
                </div>
            `;
            body.querySelector('thead')?.addEventListener('click', (e) => {
                const th = e.target.closest('[data-sort]');
                if (!th) return;
                if (nodeSortKey === th.dataset.sort) nodeSortDir *= -1;
                else { nodeSortKey = th.dataset.sort; nodeSortDir = -1; }
                renderNodes();
            });
        }

        // ─── CHAT TAB ──────────────────────────────────────────
        function renderChat() {
            const now = Math.floor(Date.now() / 1000);
            const visible = messages.slice(-80);

            body.innerHTML = `
                <div class="msh-chat-log" data-bind="chat-log">
                    ${visible.length === 0
                        ? '<div class="msh-empty" style="padding:30px;text-align:center">No messages yet</div>'
                        : visible.map(m => {
                            const sender = _esc(m.from_short || m.from_name || m.from || 'Unknown');
                            const text = _esc(m.text || '');
                            const time = m.timestamp ? new Date(m.timestamp * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '';
                            const self = m.is_self;
                            return `<div class="msh-msg${self ? ' msh-msg-self' : ''}">
                                <span class="msh-msg-from">${sender}</span>
                                <span class="msh-msg-time">${time}</span>
                                <div class="msh-msg-text">${text}</div>
                            </div>`;
                        }).join('')}
                </div>
                <div class="msh-chat-input">
                    <input type="text" class="msh-input" data-bind="chat-input" maxlength="${MSG_CHAR_LIMIT}" placeholder="Type a message..." autocomplete="off" />
                    <span class="msh-char-count" data-bind="char-count">${MSG_CHAR_LIMIT}</span>
                    <button class="msh-btn msh-btn-send" data-action="send">SEND</button>
                </div>
            `;

            // Scroll chat to bottom
            const log = body.querySelector('[data-bind="chat-log"]');
            if (log) log.scrollTop = log.scrollHeight;

            // Wire send
            const input = body.querySelector('[data-bind="chat-input"]');
            const sendBtn = body.querySelector('[data-action="send"]');
            const charCount = body.querySelector('[data-bind="char-count"]');

            if (input) {
                input.focus();
                input.addEventListener('input', () => {
                    const rem = MSG_CHAR_LIMIT - input.value.length;
                    if (charCount) { charCount.textContent = rem; charCount.style.color = rem < 20 ? '#ff2a6d' : '#888'; }
                });
                input.addEventListener('keydown', (e) => {
                    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); e.stopPropagation(); doSend(input); }
                });
            }
            if (sendBtn) sendBtn.addEventListener('click', () => doSend(input));
        }

        async function doSend(input) {
            if (!input) return;
            const text = input.value.trim();
            if (!text) return;
            input.value = '';
            messages.push({ from: 'You', from_short: 'You', text, timestamp: Math.floor(Date.now() / 1000), is_self: true });
            renderChat();
            try { await fetch(API + '/send', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text }) }); } catch (_) {}
        }

        // ─── CONFIG TAB ─────────────────────────────────────────
        function renderConfig() {
            const di = deviceInfo;
            body.innerHTML = `
                <div class="msh-section-label">DEVICE</div>
                <div class="msh-config-grid">
                    <div class="msh-cfg-row"><span class="msh-cfg-lbl">Node ID</span><span class="msh-cfg-val">${_esc(di.node_id || '--')}</span></div>
                    <div class="msh-cfg-row"><span class="msh-cfg-lbl">Name</span><span class="msh-cfg-val">${_esc(di.long_name || '--')}</span></div>
                    <div class="msh-cfg-row"><span class="msh-cfg-lbl">Short</span><span class="msh-cfg-val">${_esc(di.short_name || '--')}</span></div>
                    <div class="msh-cfg-row"><span class="msh-cfg-lbl">Hardware</span><span class="msh-cfg-val">${_esc(di.hw_model || '--')}</span></div>
                    <div class="msh-cfg-row"><span class="msh-cfg-lbl">Firmware</span><span class="msh-cfg-val">${_esc(di.firmware_version || '--')}</span></div>
                    <div class="msh-cfg-row"><span class="msh-cfg-lbl">Role</span><span class="msh-cfg-val">${_esc(di.role || '--')}</span></div>
                </div>
                <div class="msh-section-label" style="margin-top:12px">RADIO</div>
                <div class="msh-config-grid">
                    <div class="msh-cfg-row"><span class="msh-cfg-lbl">Region</span><span class="msh-cfg-val">${_esc(di.region || '--')}</span></div>
                    <div class="msh-cfg-row"><span class="msh-cfg-lbl">Modem</span><span class="msh-cfg-val">${_esc(di.modem_preset || '--')}</span></div>
                    <div class="msh-cfg-row"><span class="msh-cfg-lbl">TX Power</span><span class="msh-cfg-val">${di.tx_power || '--'} dBm</span></div>
                    <div class="msh-cfg-row"><span class="msh-cfg-lbl">Channels</span><span class="msh-cfg-val">${di.num_channels || '--'}</span></div>
                </div>
                ${(di.channels || []).length > 0 ? `
                <div class="msh-section-label" style="margin-top:12px">CHANNELS</div>
                <div class="msh-config-grid">
                    ${(di.channels || []).map(ch =>
                        `<div class="msh-cfg-row"><span class="msh-cfg-lbl">[${ch.index}] ${_esc(ch.name || 'default')}</span><span class="msh-cfg-val">${ch.role === '1' || ch.role === 'PRIMARY' ? 'PRIMARY' : ch.role === '2' || ch.role === 'SECONDARY' ? 'SECONDARY' : 'DISABLED'}</span></div>`
                    ).join('')}
                </div>` : ''}
                <div class="msh-config-actions" style="padding:8px;display:flex;gap:6px;flex-wrap:wrap;">
                    <button class="msh-btn" data-action="reboot">REBOOT</button>
                    <button class="msh-btn" data-action="refresh-config">REFRESH</button>
                </div>
            `;

            body.querySelector('[data-action="reboot"]')?.addEventListener('click', async () => {
                if (!confirm('Reboot the Meshtastic device?')) return;
                try { await fetch(API + '/device/reboot', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }); } catch (_) {}
                EventBus.emit('toast:show', { message: 'Reboot command sent', type: 'info' });
            });
            body.querySelector('[data-action="refresh-config"]')?.addEventListener('click', () => {
                fetchDeviceInfo().then(renderConfig);
            });
        }

        // ── EventBus ────────────────────────────────────────────
        const unsubs = [
            EventBus.on('mesh:text', (d) => { if (d) { messages.push(d); renderBody(); } }),
            EventBus.on('mesh:connected', fetchAll),
            EventBus.on('mesh:disconnected', fetchAll),
        ];

        // ── Auto-refresh loop ───────────────────────────────────
        const timer = setInterval(() => {
            fetchAll();
            if (activeTab === 'chat') fetchMessages();
        }, REFRESH_MS);

        // ── Init: auto-connect + fetch ──────────────────────────
        fetchAll();
        fetchMessages();
        fetchDeviceInfo();

        // Auto-detect and connect: if one radio found, connect automatically.
        // If multiple, show selection in overview tab.
        fetch(API + '/status').then(r => r.ok ? r.json() : null).then(async (d) => {
            if (d && d.connected) {
                updateConnection(d);
                return;
            }
            // Not connected — detect available ports
            try {
                const portsRes = await fetch(API + '/ports');
                if (!portsRes.ok) return;
                const portsData = await portsRes.json();
                const ports = portsData.ports || [];

                if (ports.length === 1) {
                    // One radio — auto-connect
                    connLabel.textContent = 'AUTO-CONNECTING...';
                    const cr = await fetch(API + '/connect', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ transport: 'serial', port: ports[0].port, timeout: 60 }),
                    });
                    if (cr.ok) {
                        const cd = await cr.json();
                        updateConnection(cd);
                        fetchAll();
                        fetchDeviceInfo();
                    }
                } else if (ports.length > 1) {
                    // Multiple radios — show in connection bar
                    connInfo.textContent = `${ports.length} radios detected — click CONNECT to choose`;
                } else {
                    connInfo.textContent = 'No radio detected on USB';
                }
            } catch (_) {}
        }).catch(() => {});

        // ── Cleanup ref ─────────────────────────────────────────
        panel._mshCleanup = { timer, unsubs };
    },

    unmount(bodyEl, panel) {
        if (panel._mshCleanup) {
            clearInterval(panel._mshCleanup.timer);
            panel._mshCleanup.unsubs.forEach(fn => { if (typeof fn === 'function') fn(); });
            panel._mshCleanup = null;
        }
    },
};

// ── Helpers ─────────────────────────────────────────────────────────
function _age(seconds) {
    if (!seconds || seconds < 0) return '--';
    if (seconds < 60) return seconds + 's';
    if (seconds < 3600) return Math.floor(seconds / 60) + 'm';
    if (seconds < 86400) return Math.floor(seconds / 3600) + 'h';
    return Math.floor(seconds / 86400) + 'd';
}

function _injectStyles() {
    if (document.getElementById('msh-styles')) return;
    const s = document.createElement('style');
    s.id = 'msh-styles';
    s.textContent = `
        .msh-conn-bar { display:flex; align-items:center; gap:8px; padding:6px 10px; border-bottom:1px solid #1a1a2e; background:#0a0a0f; flex-shrink:0; }
        .msh-dot { width:10px; height:10px; border-radius:50%; background:#444; flex-shrink:0; }
        .msh-dot-on { background:#05ffa1; box-shadow:0 0 6px #05ffa188; }
        .msh-conn-label { font-size:0.8rem; color:#888; font-weight:bold; letter-spacing:1px; }
        .msh-conn-info { font-size:0.7rem; color:#666; }
        .msh-tabs { display:flex; border-bottom:1px solid #1a1a2e; flex-shrink:0; background:#0e0e14; }
        .msh-tab { flex:1; padding:7px 4px; background:none; border:none; border-bottom:2px solid transparent; color:#666; font-family:inherit; font-size:0.75rem; cursor:pointer; letter-spacing:1px; transition:color 0.15s,border-color 0.15s; }
        .msh-tab:hover { color:#aaa; }
        .msh-tab-active { color:#00f0ff; border-bottom-color:#00f0ff; }
        .msh-body { flex:1; overflow-y:auto; min-height:0; display:flex; flex-direction:column; }
        .msh-btn { font-family:inherit; font-size:0.7rem; padding:4px 10px; background:rgba(0,240,255,0.06); border:1px solid rgba(0,240,255,0.2); color:#00f0ff; border-radius:3px; cursor:pointer; transition:background 0.15s; }
        .msh-btn:hover { background:rgba(0,240,255,0.15); }
        .msh-btn:disabled { opacity:0.4; cursor:not-allowed; }
        .msh-btn-connect { background:rgba(5,255,161,0.1); border-color:rgba(5,255,161,0.3); color:#05ffa1; }
        .msh-btn-connect:hover { background:rgba(5,255,161,0.2); }
        .msh-btn-disconnect { background:rgba(255,42,109,0.08); border-color:rgba(255,42,109,0.2); color:#ff2a6d; }
        .msh-btn-send { background:rgba(5,255,161,0.1); border-color:rgba(5,255,161,0.3); color:#05ffa1; }
        .msh-stats { display:grid; grid-template-columns:1fr 1fr; gap:8px; padding:10px; }
        .msh-stat { text-align:center; }
        .msh-stat-val { font-size:1.6rem; font-weight:bold; }
        .msh-stat-lbl { font-size:0.7rem; color:#666; letter-spacing:1px; margin-top:2px; }
        .msh-section-label { font-size:0.7rem; color:#00f0ff88; letter-spacing:2px; padding:6px 10px 2px; text-transform:uppercase; }
        .msh-recent { padding:0 6px 6px; }
        .msh-recent-row { display:flex; gap:6px; padding:3px 6px; font-size:0.75rem; border-bottom:1px solid #ffffff06; align-items:center; }
        .msh-recent-name { color:#ccc; flex:0 0 70px; }
        .msh-recent-hw { color:#666; flex:1; font-size:0.65rem; }
        .msh-recent-bat { color:#fcee0a; width:40px; text-align:right; }
        .msh-recent-age { color:#888; width:40px; text-align:right; }
        .msh-empty { color:#555; font-size:0.75rem; }
        .msh-node-count { padding:4px 10px; font-size:0.75rem; color:#888; border-bottom:1px solid #1a1a2e; flex-shrink:0; }
        .msh-table { width:100%; border-collapse:collapse; font-size:0.72rem; }
        .msh-th { padding:4px 6px; color:#888; border-bottom:1px solid #1a1a2e; cursor:pointer; user-select:none; white-space:nowrap; font-size:0.7rem; }
        .msh-th:hover { color:#00f0ff; }
        .msh-td { padding:3px 6px; color:#ccc; border-bottom:1px solid #ffffff06; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
        .msh-tr:hover .msh-td { background:rgba(0,240,255,0.03); }
        .msh-chat-log { flex:1; overflow-y:auto; padding:6px 10px; min-height:0; }
        .msh-msg { margin-bottom:6px; }
        .msh-msg-self { text-align:right; }
        .msh-msg-from { font-size:0.7rem; font-weight:bold; color:#00f0ff; }
        .msh-msg-self .msh-msg-from { color:#05ffa1; }
        .msh-msg-time { font-size:0.6rem; color:#555; margin-left:4px; }
        .msh-msg-text { color:#ccc; margin-top:1px; word-break:break-word; font-size:0.75rem; }
        .msh-chat-input { display:flex; gap:4px; padding:6px 10px; border-top:1px solid #1a1a2e; align-items:center; flex-shrink:0; }
        .msh-input { flex:1; background:#0a0a0f; border:1px solid #1a1a2e; color:#ccc; padding:5px 8px; font-family:inherit; font-size:0.75rem; border-radius:3px; outline:none; }
        .msh-input:focus { border-color:#00f0ff66; }
        .msh-char-count { font-size:0.6rem; color:#888; min-width:24px; text-align:right; }
        .msh-config-grid { padding:0 10px; }
        .msh-cfg-row { display:flex; justify-content:space-between; padding:3px 0; border-bottom:1px solid #ffffff06; font-size:0.75rem; }
        .msh-cfg-lbl { color:#888; }
        .msh-cfg-val { color:#ccc; }
        .msh-config-actions { margin-top:8px; }
    `;
    document.head.appendChild(s);
}
