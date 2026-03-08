// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// Fleet Nodes Panel — tritium-edge sensor node monitoring
// Displays live status of ESP32 edge sensor nodes reporting to the fleet server.
// Subscribes to: fleet:heartbeat, fleet:device_update, fleet:ble_presence,
//                fleet:registered, fleet:offline

import { EventBus } from '../events.js';

function _esc(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = String(text);
    return div.innerHTML;
}

// ============================================================
// Status helpers
// ============================================================

const STALE_THRESHOLD_S = 60;   // yellow after 60s without heartbeat
const OFFLINE_THRESHOLD_S = 180; // red after 180s without heartbeat

function _healthClass(classification) {
    switch ((classification || '').toLowerCase()) {
        case 'healthy':  return 'fleet-health-healthy';
        case 'warning':  return 'fleet-health-warning';
        case 'critical': return 'fleet-health-critical';
        default:         return 'fleet-health-unknown';
    }
}

function _healthColor(classification) {
    switch ((classification || '').toLowerCase()) {
        case 'healthy':  return 'var(--green)';
        case 'warning':  return 'var(--yellow, #fcee0a)';
        case 'critical': return 'var(--magenta)';
        default:         return 'var(--text-dim, #888)';
    }
}

function _timeAgo(ts) {
    if (!ts) return 'never';
    const secs = Math.floor(Date.now() / 1000 - ts);
    if (secs < 5) return 'just now';
    if (secs < 60) return `${secs}s ago`;
    if (secs < 3600) return `${Math.floor(secs / 60)}m ago`;
    if (secs < 86400) return `${Math.floor(secs / 3600)}h ago`;
    return `${Math.floor(secs / 86400)}d ago`;
}

function _formatBytes(bytes) {
    if (bytes === undefined || bytes === null) return '--';
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function _batteryIcon(pct) {
    if (pct === undefined || pct === null) return '';
    const color = pct > 50 ? 'var(--green)' : pct > 20 ? 'var(--yellow, #fcee0a)' : 'var(--magenta)';
    return `<span style="color:${color}">${pct}%</span>`;
}

function _nodeStatus(node) {
    if (node._online === false) return 'offline';
    const lastSeen = node._last_seen_ts || 0;
    if (lastSeen === 0) return 'unknown';
    const age = (Date.now() / 1000) - lastSeen;
    if (age > OFFLINE_THRESHOLD_S) return 'offline';
    if (age > STALE_THRESHOLD_S) return 'stale';
    return 'online';
}

function _statusDot(status) {
    switch (status) {
        case 'online':  return 'panel-dot panel-dot-green';
        case 'stale':   return 'panel-dot panel-dot-yellow';
        case 'offline': return 'panel-dot panel-dot-red';
        default:        return 'panel-dot panel-dot-neutral';
    }
}

function _statusLabel(status) {
    return (status || 'unknown').toUpperCase();
}

function _rssiBar(rssi) {
    if (rssi === undefined || rssi === null) return '--';
    // WiFi RSSI: -30 (excellent) to -90 (poor)
    const clamped = Math.max(-90, Math.min(-30, rssi));
    const pct = Math.round(((clamped + 90) / 60) * 100);
    const color = pct > 60 ? 'var(--green)' : pct > 30 ? 'var(--yellow, #fcee0a)' : 'var(--magenta)';
    return `<span class="fleet-rssi-bar" title="${rssi} dBm">
        <span class="fleet-rssi-fill" style="width:${pct}%;background:${color}"></span>
        <span class="fleet-rssi-label mono">${rssi}</span>
    </span>`;
}

function _formatUptime(seconds) {
    if (!seconds && seconds !== 0) return '--';
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    if (h > 0) return `${h}h ${m}m`;
    return `${m}m`;
}

// ============================================================
// Panel Definition
// ============================================================

export const FleetPanelDef = {
    id: 'fleet',
    title: 'FLEET NODES',
    defaultPosition: { x: null, y: null },
    defaultSize: { w: 620, h: 520 },

    create(panel) {
        const el = document.createElement('div');
        el.className = 'fleet-panel-inner';
        el.innerHTML = `
            <div class="fleet-toolbar">
                <span class="fleet-node-count mono" data-bind="node-count">0 nodes</span>
                <span class="fleet-refresh-indicator mono" data-bind="refresh-indicator">--</span>
                <button class="panel-action-btn" data-action="refresh" title="Refresh node list">REFRESH</button>
            </div>
            <div class="fleet-device-table-wrap" data-bind="device-table-wrap">
                <table class="fleet-device-table" data-bind="device-table">
                    <thead>
                        <tr>
                            <th></th>
                            <th>DEVICE</th>
                            <th>HEALTH</th>
                            <th>LAST SEEN</th>
                            <th>FW</th>
                            <th>HEAP</th>
                            <th>BAT</th>
                            <th>RSSI</th>
                        </tr>
                    </thead>
                    <tbody data-bind="device-tbody">
                        <tr><td colspan="8" class="panel-empty">Waiting for fleet data...</td></tr>
                    </tbody>
                </table>
            </div>
            <div class="fleet-node-detail" data-bind="node-detail" style="display:none"></div>
            <div class="fleet-map-section" data-bind="fleet-map">
                <div class="panel-section-label">FLEET MAP</div>
                <div class="fleet-map-placeholder" data-bind="map-placeholder">
                    <span class="fleet-map-icon">&#x25C9;</span>
                    <span>Map view coming soon</span>
                    <span class="mono fleet-map-count" data-bind="map-node-count">0 nodes registered</span>
                </div>
            </div>
            <div class="fleet-health-bar" data-bind="health-bar" style="display:none">
                <div class="panel-section-label">FLEET HEALTH</div>
                <div class="panel-stat-row">
                    <span class="panel-stat-label">SCORE</span>
                    <span class="panel-stat-value mono" data-bind="health-score">--</span>
                </div>
                <div class="panel-stat-row">
                    <span class="panel-stat-label">NODES</span>
                    <span class="panel-stat-value mono" data-bind="health-nodes">--</span>
                </div>
                <div class="panel-stat-row">
                    <span class="panel-stat-label">ALERTS</span>
                    <span class="panel-stat-value mono" data-bind="health-alerts">--</span>
                </div>
                <div class="panel-stat-row">
                    <span class="panel-stat-label">CONFIG</span>
                    <span class="panel-stat-value mono" data-bind="health-config">--</span>
                </div>
            </div>
            <div class="fleet-config-bar" data-bind="config-bar" style="display:none">
                <div class="panel-section-label">CONFIG SYNC</div>
                <div class="panel-stat-row">
                    <span class="panel-stat-label">VERSION</span>
                    <span class="panel-stat-value mono" data-bind="config-version">--</span>
                </div>
                <div class="panel-stat-row">
                    <span class="panel-stat-label">SYNCED</span>
                    <span class="panel-stat-value mono" data-bind="config-synced">--</span>
                </div>
                <div class="panel-stat-row">
                    <span class="panel-stat-label">PENDING</span>
                    <span class="panel-stat-value mono" data-bind="config-pending">--</span>
                </div>
            </div>
            <div class="fleet-anomaly-bar" data-bind="anomaly-bar" style="display:none">
                <div class="panel-section-label" style="color:var(--magenta)">FLEET ANOMALIES</div>
                <div data-bind="anomaly-list"></div>
            </div>
            <div class="fleet-status-bar" data-bind="status">
                <span class="panel-dot panel-dot-neutral" data-bind="status-dot"></span>
                <span class="mono" data-bind="status-label">POLLING</span>
            </div>
        `;
        return el;
    },

    mount(bodyEl, panel) {
        const deviceTbodyEl = bodyEl.querySelector('[data-bind="device-tbody"]');
        const nodeCountEl = bodyEl.querySelector('[data-bind="node-count"]');
        const nodeDetailEl = bodyEl.querySelector('[data-bind="node-detail"]');
        const statusDot = bodyEl.querySelector('[data-bind="status-dot"]');
        const statusLabelEl = bodyEl.querySelector('[data-bind="status-label"]');
        const refreshBtn = bodyEl.querySelector('[data-action="refresh"]');
        const refreshIndicator = bodyEl.querySelector('[data-bind="refresh-indicator"]');
        const healthBar = bodyEl.querySelector('[data-bind="health-bar"]');
        const healthScoreEl = bodyEl.querySelector('[data-bind="health-score"]');
        const healthNodesEl = bodyEl.querySelector('[data-bind="health-nodes"]');
        const healthAlertsEl = bodyEl.querySelector('[data-bind="health-alerts"]');
        const healthConfigEl = bodyEl.querySelector('[data-bind="health-config"]');
        const configBar = bodyEl.querySelector('[data-bind="config-bar"]');
        const configVersionEl = bodyEl.querySelector('[data-bind="config-version"]');
        const configSyncedEl = bodyEl.querySelector('[data-bind="config-synced"]');
        const configPendingEl = bodyEl.querySelector('[data-bind="config-pending"]');
        const anomalyBar = bodyEl.querySelector('[data-bind="anomaly-bar"]');
        const anomalyListEl = bodyEl.querySelector('[data-bind="anomaly-list"]');
        const mapPlaceholder = bodyEl.querySelector('[data-bind="map-placeholder"]');
        const mapNodeCount = bodyEl.querySelector('[data-bind="map-node-count"]');

        // node tracking: device_id -> merged node data
        let nodes = {};
        // health report per-node classification: device_id -> { classification, anomalies, ... }
        let healthReportNodes = {};
        let selectedNodeId = null;
        let bridgeConnected = false;
        let lastRefreshTs = 0;

        // --- Refresh indicator ---
        function updateRefreshIndicator() {
            if (refreshIndicator) {
                refreshIndicator.textContent = lastRefreshTs
                    ? _timeAgo(lastRefreshTs)
                    : '--';
            }
        }

        // Update the refresh indicator every second
        const refreshTickInterval = setInterval(updateRefreshIndicator, 1000);
        panel._unsubs.push(() => clearInterval(refreshTickInterval));

        // --- Status bar ---
        function updateStatusBar() {
            const nodeArr = Object.values(nodes);
            const onlineCount = nodeArr.filter(n => _nodeStatus(n) === 'online').length;
            if (statusDot) {
                statusDot.className = bridgeConnected
                    ? 'panel-dot panel-dot-green'
                    : 'panel-dot panel-dot-neutral';
            }
            if (statusLabelEl) {
                statusLabelEl.textContent = bridgeConnected
                    ? `CONNECTED (${onlineCount} online)`
                    : 'POLLING';
            }
        }

        // --- Map placeholder ---
        function updateMapCount() {
            const count = Object.keys(nodes).length;
            if (mapNodeCount) {
                mapNodeCount.textContent = `${count} node${count !== 1 ? 's' : ''} registered`;
            }
        }

        // --- Device table rendering ---
        function renderNodes() {
            const nodeArr = Object.values(nodes);
            if (nodeCountEl) nodeCountEl.textContent = `${nodeArr.length} nodes`;

            updateMapCount();

            if (!deviceTbodyEl) return;

            if (nodeArr.length === 0) {
                deviceTbodyEl.innerHTML = '<tr><td colspan="8" class="panel-empty">Waiting for fleet data...</td></tr>';
                return;
            }

            // Sort: critical first, then warning, then healthy; within same health, online first
            const healthOrder = { critical: 0, warning: 1, healthy: 2, unknown: 3 };
            const statusOrder = { online: 0, stale: 1, unknown: 2, offline: 3 };
            nodeArr.sort((a, b) => {
                const aHealth = healthReportNodes[a.device_id || a.id]?.classification || 'unknown';
                const bHealth = healthReportNodes[b.device_id || b.id]?.classification || 'unknown';
                const hDiff = (healthOrder[aHealth] ?? 9) - (healthOrder[bHealth] ?? 9);
                if (hDiff !== 0) return hDiff;
                return (statusOrder[_nodeStatus(a)] || 9) - (statusOrder[_nodeStatus(b)] || 9);
            });

            deviceTbodyEl.innerHTML = nodeArr.map(n => {
                const deviceId = n.device_id || n.id || '';
                const status = _nodeStatus(n);
                const dotClass = _statusDot(status);
                const fw = _esc(n.version || n.firmware || '--');
                const rssi = n.rssi !== undefined ? n.rssi : (n.wifi_rssi !== undefined ? n.wifi_rssi : null);
                const lastSeen = n._last_seen_ts || 0;
                const freeHeap = n.free_heap;
                const battery = n.battery_pct ?? n.sensors?.power?.battery_pct;
                const anomalyCount = n._anomaly_count || 0;
                const isSelected = selectedNodeId === deviceId;

                // Health classification from health report
                const hrNode = healthReportNodes[deviceId] || {};
                const classification = hrNode.classification || 'unknown';
                const healthClr = _healthColor(classification);

                const anomalyBadge = anomalyCount > 0
                    ? ` <span style="color:var(--magenta);font-weight:bold" title="${anomalyCount} anomalies">!${anomalyCount}</span>`
                    : '';

                return `<tr class="fleet-device-row${isSelected ? ' active' : ''}" data-device-id="${_esc(deviceId)}">
                    <td><span class="${dotClass}"></span></td>
                    <td class="mono fleet-device-id-cell" title="${_esc(deviceId)}">${_esc(deviceId)}${anomalyBadge}</td>
                    <td class="mono" style="color:${healthClr}">${_esc(classification.toUpperCase())}</td>
                    <td class="mono">${_timeAgo(lastSeen)}</td>
                    <td class="mono">${fw}</td>
                    <td class="mono">${_formatBytes(freeHeap)}</td>
                    <td class="mono">${_batteryIcon(battery)}</td>
                    <td>${_rssiBar(rssi)}</td>
                </tr>`;
            }).join('');

            // Click handler: expand node detail
            deviceTbodyEl.querySelectorAll('.fleet-device-row').forEach(row => {
                row.addEventListener('click', () => {
                    const deviceId = row.dataset.deviceId;
                    if (selectedNodeId === deviceId) {
                        selectedNodeId = null;
                        if (nodeDetailEl) nodeDetailEl.style.display = 'none';
                    } else {
                        selectedNodeId = deviceId;
                        showNodeDetail(deviceId);
                    }
                    renderNodes();
                });
            });

            updateStatusBar();
        }

        // --- Node detail (expanded view) ---
        function showNodeDetail(deviceId) {
            if (!nodeDetailEl) return;
            const n = nodes[deviceId];
            if (!n) {
                nodeDetailEl.style.display = 'none';
                return;
            }

            const status = _nodeStatus(n);
            const rssi = n.rssi !== undefined ? n.rssi : (n.wifi_rssi !== undefined ? n.wifi_rssi : null);
            const hrNode = healthReportNodes[deviceId] || {};
            const classification = hrNode.classification || 'unknown';
            const healthClr = _healthColor(classification);

            // --- Health snapshot section ---
            let healthSnapshotHtml = `
                <div class="panel-section-label" style="color:${healthClr}">HEALTH: ${_esc(classification.toUpperCase())}</div>
                <div class="panel-stat-row"><span class="panel-stat-label">DEVICE ID</span><span class="panel-stat-value mono">${_esc(n.device_id || n.id || '--')}</span></div>
                <div class="panel-stat-row"><span class="panel-stat-label">STATUS</span><span class="panel-stat-value" style="color:${status === 'online' ? 'var(--green)' : status === 'stale' ? 'var(--yellow, #fcee0a)' : 'var(--magenta)'}">${_statusLabel(status)}</span></div>
                <div class="panel-stat-row"><span class="panel-stat-label">LAST SEEN</span><span class="panel-stat-value mono">${_timeAgo(n._last_seen_ts)}</span></div>
                <div class="panel-stat-row"><span class="panel-stat-label">IP</span><span class="panel-stat-value mono">${_esc(n.ip || '--')}</span></div>
                <div class="panel-stat-row"><span class="panel-stat-label">MAC</span><span class="panel-stat-value mono">${_esc(n.mac || '--')}</span></div>
                <div class="panel-stat-row"><span class="panel-stat-label">FIRMWARE</span><span class="panel-stat-value mono">${_esc(n.version || n.firmware || '--')}</span></div>
                <div class="panel-stat-row"><span class="panel-stat-label">BOARD</span><span class="panel-stat-value mono">${_esc(n.board || '--')}</span></div>
                <div class="panel-stat-row"><span class="panel-stat-label">WIFI RSSI</span><span class="panel-stat-value">${_rssiBar(rssi)}</span></div>
                <div class="panel-stat-row"><span class="panel-stat-label">UPTIME</span><span class="panel-stat-value mono">${_formatUptime(n.uptime_s || n.uptime)}</span></div>
                <div class="panel-stat-row"><span class="panel-stat-label">FREE HEAP</span><span class="panel-stat-value mono">${_formatBytes(n.free_heap)}</span></div>
                <div class="panel-stat-row"><span class="panel-stat-label">PARTITION</span><span class="panel-stat-value mono">${_esc(n.partition || '--')}</span></div>
            `;

            // Battery if available
            const battery = n.battery_pct ?? n.sensors?.power?.battery_pct;
            if (battery !== undefined && battery !== null) {
                healthSnapshotHtml += `<div class="panel-stat-row"><span class="panel-stat-label">BATTERY</span><span class="panel-stat-value mono">${_batteryIcon(battery)}</span></div>`;
            }

            // Health report extra fields (from fleet:health_report per-node data)
            if (hrNode.score !== undefined) {
                const scorePct = Math.round(hrNode.score * 100);
                const scoreClr = scorePct >= 80 ? 'var(--green)' : scorePct >= 50 ? 'var(--yellow, #fcee0a)' : 'var(--magenta)';
                healthSnapshotHtml += `<div class="panel-stat-row"><span class="panel-stat-label">HEALTH SCORE</span><span class="panel-stat-value mono" style="color:${scoreClr}">${scorePct}%</span></div>`;
            }

            // --- Diagnostics section ---
            const diag = n._diagnostics || {};
            const health = diag.health || {};
            let diagHtml = '';
            if (Object.keys(health).length > 0) {
                diagHtml += '<div class="panel-section-label">DIAGNOSTICS</div>';
                if (health.cpu_temp_c) diagHtml += `<div class="panel-stat-row"><span class="panel-stat-label">CPU TEMP</span><span class="panel-stat-value mono">${health.cpu_temp_c.toFixed(1)}C</span></div>`;
                if (health.min_free_heap) diagHtml += `<div class="panel-stat-row"><span class="panel-stat-label">MIN HEAP</span><span class="panel-stat-value mono">${_formatBytes(health.min_free_heap)}</span></div>`;
                if (health.loop_time_us) diagHtml += `<div class="panel-stat-row"><span class="panel-stat-label">LOOP TIME</span><span class="panel-stat-value mono">${health.loop_time_us} us</span></div>`;
                if (health.max_loop_time_us) diagHtml += `<div class="panel-stat-row"><span class="panel-stat-label">MAX LOOP</span><span class="panel-stat-value mono">${health.max_loop_time_us} us</span></div>`;
                if (health.display?.frame_us) diagHtml += `<div class="panel-stat-row"><span class="panel-stat-label">FRAME TIME</span><span class="panel-stat-value mono">${health.display.frame_us} us</span></div>`;
                if (health.display?.max_frame_us) diagHtml += `<div class="panel-stat-row"><span class="panel-stat-label">MAX FRAME</span><span class="panel-stat-value mono">${health.display.max_frame_us} us</span></div>`;
                if (health.i2c_errors) diagHtml += `<div class="panel-stat-row"><span class="panel-stat-label">I2C ERRORS</span><span class="panel-stat-value mono" style="color:${health.i2c_errors > 0 ? 'var(--magenta)' : 'inherit'}">${health.i2c_errors}</span></div>`;
                if (health.wifi_disconnects) diagHtml += `<div class="panel-stat-row"><span class="panel-stat-label">WiFi DROPS</span><span class="panel-stat-value mono">${health.wifi_disconnects}</span></div>`;
                if (health.reboot_count !== undefined) diagHtml += `<div class="panel-stat-row"><span class="panel-stat-label">REBOOTS</span><span class="panel-stat-value mono">${health.reboot_count}</span></div>`;
                if (health.reset_reason) diagHtml += `<div class="panel-stat-row"><span class="panel-stat-label">LAST RESET</span><span class="panel-stat-value mono">${_esc(health.reset_reason)}</span></div>`;
            }

            // --- I2C slave health table ---
            const i2cSlaves = diag.i2c_slaves || health.i2c_slaves || hrNode.i2c_slaves || [];
            let i2cHtml = '';
            if (i2cSlaves.length > 0) {
                i2cHtml += '<div class="panel-section-label">I2C BUS HEALTH</div>';
                i2cHtml += '<table class="fleet-i2c-table"><thead><tr><th>ADDR</th><th>OK</th><th>NACK</th><th>TIMEOUT</th><th>RATE</th><th>LAT</th></tr></thead><tbody>';
                i2cHtml += i2cSlaves.map(s => {
                    const total = (s.ok || 0) + (s.nack || 0) + (s.timeout || 0);
                    const rate = total > 0 ? (s.ok || 0) / total : 0;
                    const pct = Math.round(rate * 100);
                    const color = pct === 100 ? 'var(--green)' : pct > 95 ? 'var(--yellow, #fcee0a)' : 'var(--magenta)';
                    return `<tr>
                        <td class="mono">${_esc(s.addr || s.address || '--')}</td>
                        <td class="mono">${s.ok || 0}</td>
                        <td class="mono" style="color:${(s.nack || 0) > 0 ? 'var(--magenta)' : 'inherit'}">${s.nack || 0}</td>
                        <td class="mono" style="color:${(s.timeout || 0) > 0 ? 'var(--magenta)' : 'inherit'}">${s.timeout || 0}</td>
                        <td class="mono" style="color:${color}">${pct}%</td>
                        <td class="mono">${s.lat_us !== undefined ? s.lat_us + 'us' : '--'}</td>
                    </tr>`;
                }).join('');
                i2cHtml += '</tbody></table>';
            }

            // --- Diagnostic events (recent) ---
            const diagEvents = diag.events || n._diag_events || hrNode.events || [];
            let eventsHtml = '';
            if (diagEvents.length > 0) {
                eventsHtml += '<div class="panel-section-label">RECENT EVENTS</div>';
                eventsHtml += '<div class="fleet-detail-events">';
                eventsHtml += diagEvents.slice(0, 10).map(evt => {
                    const ts = evt.timestamp ? _timeAgo(evt.timestamp) : '';
                    const sevColor = evt.severity === 'critical' ? 'var(--magenta)'
                        : evt.severity === 'warning' ? 'var(--yellow, #fcee0a)'
                        : 'var(--text-dim)';
                    return `<div class="fleet-event-row">
                        <span class="mono" style="color:${sevColor};min-width:60px">${_esc((evt.severity || 'info').toUpperCase())}</span>
                        <span class="mono" style="flex:1">${_esc(evt.message || evt.description || evt.type || '--')}</span>
                        <span class="mono" style="color:var(--text-dim);font-size:0.8em">${ts}</span>
                    </div>`;
                }).join('');
                eventsHtml += '</div>';
            }

            // --- Active anomalies ---
            const anomalies = n._anomalies || diag.anomalies || hrNode.anomalies || [];
            let anomalyHtml = '';
            if (anomalies.length > 0) {
                anomalyHtml = '<div class="panel-section-label" style="color:var(--magenta)">ACTIVE ANOMALIES (' + anomalies.length + ')</div>';
                anomalyHtml += anomalies.map(a => {
                    const sev = a.severity_score !== undefined ? Math.round(a.severity_score * 100) + '%' : '';
                    const subsys = _esc(a.subsystem || a.type || 'UNKNOWN');
                    const desc = _esc(a.description || a.message || '');
                    const since = a.first_seen ? `since ${_timeAgo(a.first_seen)}` : '';
                    return `<div class="panel-stat-row" style="color:var(--magenta)">
                        <span class="panel-stat-label">${subsys}</span>
                        <span class="panel-stat-value mono">${desc} ${sev} <span style="color:var(--text-dim);font-size:0.8em">${since}</span></span>
                    </div>`;
                }).join('');
            }

            // --- Sensor summary ---
            const sensors = n.sensors || {};
            let sensorHtml = '';
            for (const [sType, sData] of Object.entries(sensors)) {
                if (sType === 'ble_scanner') continue;
                const val = typeof sData === 'object' ? JSON.stringify(sData) : String(sData);
                sensorHtml += `<div class="panel-stat-row">
                    <span class="panel-stat-label">${_esc(sType.toUpperCase())}</span>
                    <span class="panel-stat-value mono">${_esc(val)}</span>
                </div>`;
            }

            // BLE devices list
            const bleDevices = n.sensors?.ble_scanner?.devices
                || n.ble_devices || [];
            let bleHtml = '<span class="panel-empty">No BLE devices</span>';
            if (bleDevices.length > 0) {
                bleHtml = bleDevices.map(d => {
                    const addr = _esc(d.addr || d.mac || '--');
                    const name = _esc(d.name || '');
                    const dRssi = d.rssi !== undefined ? `${d.rssi} dBm` : '--';
                    return `<div class="panel-stat-row">
                        <span class="panel-stat-label mono">${addr}${name ? ' (' + name + ')' : ''}</span>
                        <span class="panel-stat-value">${dRssi}</span>
                    </div>`;
                }).join('');
            }

            // --- Close button ---
            const closeBtn = `<button class="panel-action-btn fleet-detail-close" data-action="close-detail" title="Close detail">X</button>`;

            nodeDetailEl.style.display = '';
            nodeDetailEl.innerHTML = `
                <div class="fleet-detail-header">
                    <div class="panel-section-label" style="flex:1">NODE DETAIL</div>
                    ${closeBtn}
                </div>
                ${healthSnapshotHtml}
                ${diagHtml}
                ${i2cHtml}
                ${eventsHtml}
                ${anomalyHtml}
                ${sensorHtml ? '<div class="panel-section-label">SENSORS</div>' + sensorHtml : ''}
                <div class="panel-section-label">BLE DEVICES (${bleDevices.length})</div>
                ${bleHtml}
            `;

            // Close button handler
            const closeBtnEl = nodeDetailEl.querySelector('[data-action="close-detail"]');
            if (closeBtnEl) {
                closeBtnEl.addEventListener('click', (e) => {
                    e.stopPropagation();
                    selectedNodeId = null;
                    nodeDetailEl.style.display = 'none';
                    renderNodes();
                });
            }
        }

        // --- Data fetch ---
        async function fetchNodes() {
            try {
                const res = await fetch('/api/fleet/nodes');
                if (!res.ok) return;
                const data = await res.json();
                const nodeArr = data.nodes || [];
                for (const n of nodeArr) {
                    const id = n.device_id || n.id;
                    if (!id) continue;
                    // Preserve _last_seen_ts if we already had it
                    const existing = nodes[id];
                    nodes[id] = {
                        ...n,
                        _last_seen_ts: n._last_seen_ts || (existing && existing._last_seen_ts) || Date.now() / 1000,
                        _online: n._online !== undefined ? n._online : true,
                    };
                }
                lastRefreshTs = Date.now() / 1000;
                updateRefreshIndicator();
                renderNodes();
                if (selectedNodeId) showNodeDetail(selectedNodeId);
            } catch (_) {}
        }

        async function fetchHealthReport() {
            try {
                const res = await fetch('/api/fleet/health-report');
                if (!res.ok) return;
                const data = await res.json();
                onHealthReport(data);
            } catch (_) {}
        }

        // --- Event handlers ---
        function onHeartbeat(data) {
            if (!data || !data.device_id) return;
            const id = data.device_id;
            nodes[id] = {
                ...nodes[id],
                ...data,
                _last_seen_ts: Date.now() / 1000,
                _online: data.online !== false,
            };
            renderNodes();
            if (selectedNodeId === id) showNodeDetail(id);
        }

        function onDeviceUpdate(data) {
            if (!data) return;
            const devices = data.devices || [];
            for (const dev of devices) {
                const id = dev.device_id || dev.id;
                if (!id) continue;
                const existing = nodes[id];
                nodes[id] = {
                    ...dev,
                    _last_seen_ts: Date.now() / 1000,
                    _online: dev._online !== undefined ? dev._online : true,
                };
            }
            renderNodes();
            if (selectedNodeId) showNodeDetail(selectedNodeId);
        }

        function onOffline(data) {
            if (!data || !data.device_id) return;
            if (nodes[data.device_id]) {
                nodes[data.device_id]._online = false;
            }
            renderNodes();
            if (selectedNodeId === data.device_id) showNodeDetail(data.device_id);
        }

        function onRegistered(data) {
            if (!data || !data.device_id) return;
            nodes[data.device_id] = {
                ...nodes[data.device_id],
                ...data,
                _last_seen_ts: Date.now() / 1000,
                _online: true,
            };
            renderNodes();
        }

        // --- Diagnostics event handler ---
        function onNodeDiag(data) {
            if (!data || !data.device_id) return;
            const id = data.device_id;
            if (nodes[id]) {
                nodes[id]._diagnostics = data.diagnostics || {};
            }
            if (selectedNodeId === id) showNodeDetail(id);
        }

        function onNodeAnomaly(data) {
            if (!data || !data.device_id) return;
            const id = data.device_id;
            if (nodes[id]) {
                nodes[id]._anomalies = data.anomalies || [];
                nodes[id]._anomaly_count = data.count || 0;
            }
            renderNodes();
            if (selectedNodeId === id) showNodeDetail(id);
        }

        // --- Config sync handler ---
        function onConfigSync(data) {
            if (!data) return;
            if (configBar) configBar.style.display = '';
            if (configVersionEl) configVersionEl.textContent = data.config_version || '--';
            const synced = data.nodes_synced ?? 0;
            const total = data.nodes_total ?? 0;
            if (configSyncedEl) {
                configSyncedEl.textContent = `${synced}/${total}`;
                configSyncedEl.style.color = synced === total && total > 0
                    ? 'var(--green)' : 'var(--yellow, #fcee0a)';
            }
            const pending = data.nodes_pending || [];
            if (configPendingEl) {
                configPendingEl.textContent = pending.length > 0
                    ? pending.join(', ') : 'none';
                configPendingEl.style.color = pending.length > 0
                    ? 'var(--magenta)' : 'inherit';
            }
        }

        // --- Dashboard handler ---
        function onDashboard(data) {
            if (!data) return;
            if (healthBar) healthBar.style.display = '';
            const score = data.health_score ?? 0;
            if (healthScoreEl) {
                const pct = Math.round(score * 100);
                healthScoreEl.textContent = `${pct}%`;
                healthScoreEl.style.color = pct >= 80 ? 'var(--green)' : pct >= 50 ? 'var(--yellow, #fcee0a)' : 'var(--magenta)';
            }
            if (healthNodesEl) {
                healthNodesEl.textContent = `${data.online_count ?? 0}/${data.total_nodes ?? 0} online`;
            }
            const critAlerts = data.critical_alerts ?? 0;
            if (healthAlertsEl) {
                healthAlertsEl.textContent = critAlerts > 0
                    ? `${critAlerts} critical / ${data.alert_count ?? 0} total`
                    : `${data.alert_count ?? 0} total`;
                healthAlertsEl.style.color = critAlerts > 0 ? 'var(--magenta)' : 'inherit';
            }
            const syncRatio = data.sync_ratio ?? 1;
            if (healthConfigEl) {
                const syncPct = Math.round(syncRatio * 100);
                healthConfigEl.textContent = `${syncPct}% synced (${data.drifted_count ?? 0} drifted)`;
                healthConfigEl.style.color = syncPct === 100 ? 'var(--green)' : 'var(--yellow, #fcee0a)';
            }
        }

        // --- Fleet anomalies handler ---
        function onFleetAnomalies(data) {
            if (!data) return;
            const anomalies = data.anomalies || [];
            if (anomalies.length === 0) {
                if (anomalyBar) anomalyBar.style.display = 'none';
                return;
            }
            if (anomalyBar) anomalyBar.style.display = '';
            if (anomalyListEl) {
                anomalyListEl.innerHTML = anomalies.map(a => {
                    const affected = (a.affected_nodes || []).join(', ') || '--';
                    const sev = a.severity !== undefined ? Math.round(a.severity * 100) + '%' : '';
                    return `<div class="panel-stat-row" style="color:var(--magenta)">
                        <span class="panel-stat-label">${_esc(a.type || 'UNKNOWN')}</span>
                        <span class="panel-stat-value mono">${_esc(affected)} ${sev}</span>
                    </div>`;
                }).join('');
            }
        }

        // --- Health report handler ---
        function onHealthReport(data) {
            if (!data) return;
            // Update node counts in health bar if dashboard hasn't populated it
            if (healthBar && !healthScoreEl?.textContent?.includes('%')) {
                healthBar.style.display = '';
            }

            // Populate per-node health classifications from report
            const reportNodes = data.nodes || [];
            for (const rn of reportNodes) {
                const id = rn.device_id || rn.id;
                if (!id) continue;
                healthReportNodes[id] = {
                    classification: rn.classification || rn.status || 'unknown',
                    score: rn.score ?? rn.health_score,
                    anomalies: rn.anomalies || [],
                    events: rn.events || rn.recent_events || [],
                    i2c_slaves: rn.i2c_slaves || [],
                };
                // Also update anomaly count on the main node if present
                if (nodes[id] && rn.anomalies) {
                    nodes[id]._anomaly_count = rn.anomalies.length;
                    nodes[id]._anomalies = rn.anomalies;
                }
            }

            // Update fleet-level anomaly count
            if (data.anomaly_count !== undefined && healthAlertsEl) {
                const crit = data.critical ?? 0;
                const warn = data.warning ?? 0;
                if (crit > 0) {
                    healthAlertsEl.textContent = `${crit} critical / ${data.anomaly_count} total`;
                    healthAlertsEl.style.color = 'var(--magenta)';
                }
            }

            // Update health node counts
            if (healthNodesEl && data.total_nodes !== undefined) {
                const healthy = data.healthy ?? 0;
                const warn = data.warning ?? 0;
                const crit = data.critical ?? 0;
                healthNodesEl.innerHTML = `<span style="color:var(--green)">${healthy}</span> / <span style="color:var(--yellow, #fcee0a)">${warn}</span> / <span style="color:var(--magenta)">${crit}</span>`;
            }

            renderNodes();
            if (selectedNodeId) showNodeDetail(selectedNodeId);
        }

        async function fetchConfigSync() {
            try {
                const res = await fetch('/api/fleet/config');
                if (!res.ok) return;
                const data = await res.json();
                onConfigSync(data);
            } catch (_) {}
        }

        async function fetchDashboard() {
            try {
                const res = await fetch('/api/fleet/dashboard');
                if (!res.ok) return;
                const data = await res.json();
                onDashboard({
                    health_score: data.health?.score ?? 0,
                    total_nodes: data.health?.total_nodes ?? 0,
                    online_count: data.health?.online_count ?? 0,
                    synced_count: data.config?.synced_count ?? 0,
                    drifted_count: data.config?.drifted_count ?? 0,
                    sync_ratio: data.config?.sync_ratio ?? 1,
                    alert_count: data.alerts?.recent_count ?? 0,
                    critical_alerts: data.alerts?.critical ?? 0,
                    server_uptime_s: data.server_uptime_s ?? 0,
                });
            } catch (_) {}
        }

        // --- EventBus subscriptions ---
        panel._unsubs.push(
            EventBus.on('fleet:heartbeat', onHeartbeat),
            EventBus.on('fleet:device_update', onDeviceUpdate),
            EventBus.on('fleet:offline', onOffline),
            EventBus.on('fleet:registered', onRegistered),
            EventBus.on('fleet:node_diag', onNodeDiag),
            EventBus.on('fleet:node_anomaly', onNodeAnomaly),
            EventBus.on('fleet:connected', () => {
                bridgeConnected = true;
                updateStatusBar();
            }),
            EventBus.on('fleet:disconnected', () => {
                bridgeConnected = false;
                updateStatusBar();
            }),
            EventBus.on('fleet:config_sync', onConfigSync),
            EventBus.on('fleet:dashboard', onDashboard),
            EventBus.on('fleet:health_report', onHealthReport),
            EventBus.on('fleet:anomalies', onFleetAnomalies),
        );

        // Refresh button — fetch all data sources
        if (refreshBtn) {
            refreshBtn.addEventListener('click', () => {
                fetchNodes();
                fetchHealthReport();
                fetchDashboard();
                fetchConfigSync();
            });
        }

        // Auto-refresh every 10s
        const refreshInterval = setInterval(() => {
            fetchNodes();
            fetchHealthReport();
        }, 10000);
        panel._unsubs.push(() => clearInterval(refreshInterval));

        // Initial fetch
        fetchNodes();
        fetchHealthReport();
        fetchConfigSync();
        fetchDashboard();
        updateStatusBar();
    },

    unmount(bodyEl) {
        // _unsubs cleaned up by Panel base class
    },
};
