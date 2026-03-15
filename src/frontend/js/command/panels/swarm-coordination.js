// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// SPDX-License-Identifier: AGPL-3.0

/**
 * Swarm Coordination Panel — visualize and control multi-robot formations.
 *
 * Shows formation shapes (line, wedge, circle, diamond) with unit positions
 * and formation center. Animates unit movement along patrol routes.
 * Integrates with the map via overlay rendering.
 */

const SwarmCoordination = (() => {
    let swarms = [];
    let selectedSwarmId = null;
    let animationFrame = null;
    let panelEl = null;
    let canvasEl = null;
    let ctx = null;

    const FORMATION_COLORS = {
        line: '#00f0ff',
        wedge: '#ff2a6d',
        circle: '#05ffa1',
        diamond: '#fcee0a',
        column: '#00f0ff',
        staggered: '#ff2a6d',
    };

    const MEMBER_RADIUS = 6;
    const CENTER_RADIUS = 4;

    async function fetchSwarms() {
        try {
            const resp = await fetch('/api/swarm/swarms');
            if (!resp.ok) return;
            const data = await resp.json();
            swarms = data.swarms || [];
        } catch (e) {
            console.warn('Swarm fetch error:', e);
        }
    }

    async function createSwarm(name, formation, spacing) {
        try {
            const resp = await fetch('/api/swarm/swarms', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name, formation, spacing }),
            });
            if (!resp.ok) return null;
            const data = await resp.json();
            await fetchSwarms();
            render();
            return data.swarm;
        } catch (e) {
            console.warn('Swarm create error:', e);
            return null;
        }
    }

    async function issueCommand(swarmId, command, waypoints, formation) {
        try {
            const body = { command };
            if (waypoints) body.waypoints = waypoints;
            if (formation) body.formation = formation;
            const resp = await fetch(`/api/swarm/swarms/${swarmId}/command`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });
            if (!resp.ok) return null;
            const data = await resp.json();
            await fetchSwarms();
            render();
            return data.swarm;
        } catch (e) {
            console.warn('Swarm command error:', e);
            return null;
        }
    }

    async function addMember(swarmId, deviceId, assetType) {
        try {
            const resp = await fetch(`/api/swarm/swarms/${swarmId}/members`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    device_id: deviceId || '',
                    asset_type: assetType || 'rover',
                }),
            });
            if (!resp.ok) return null;
            await fetchSwarms();
            render();
        } catch (e) {
            console.warn('Member add error:', e);
        }
    }

    function drawFormation(swarm) {
        if (!ctx || !canvasEl) return;

        const color = FORMATION_COLORS[swarm.formation_type] || '#00f0ff';
        const members = swarm.members || [];
        const cx = canvasEl.width / 2;
        const cy = canvasEl.height / 2;
        const scale = 8; // pixels per meter

        // Draw formation shape outline
        ctx.strokeStyle = color;
        ctx.lineWidth = 1;
        ctx.globalAlpha = 0.3;

        if (swarm.formation_type === 'circle' && members.length > 2) {
            const radius = swarm.spacing * Math.max(1, members.length) / (2 * Math.PI) * scale;
            ctx.beginPath();
            ctx.arc(cx, cy, radius, 0, Math.PI * 2);
            ctx.stroke();
        } else if (swarm.formation_type === 'diamond' && members.length >= 4) {
            const s = swarm.spacing * scale;
            ctx.beginPath();
            ctx.moveTo(cx, cy - s);
            ctx.lineTo(cx + s, cy);
            ctx.lineTo(cx, cy + s);
            ctx.lineTo(cx - s, cy);
            ctx.closePath();
            ctx.stroke();
        }

        ctx.globalAlpha = 1.0;

        // Draw formation center
        ctx.fillStyle = '#ffffff';
        ctx.beginPath();
        ctx.arc(cx, cy, CENTER_RADIUS, 0, Math.PI * 2);
        ctx.fill();

        // Draw heading indicator
        const headRad = (swarm.heading || 0) * Math.PI / 180;
        ctx.strokeStyle = '#ffffff';
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.moveTo(cx, cy);
        ctx.lineTo(
            cx + Math.cos(headRad) * 20,
            cy - Math.sin(headRad) * 20
        );
        ctx.stroke();

        // Draw members
        members.forEach((member, i) => {
            const dx = (member.position_x - swarm.center_x) * scale;
            const dy = -(member.position_y - swarm.center_y) * scale;
            const mx = cx + dx;
            const my = cy + dy;

            // Member dot
            const memberColor = member.status === 'active' ? color :
                                member.status === 'disabled' ? '#666' : '#ff6600';
            ctx.fillStyle = memberColor;
            ctx.beginPath();
            ctx.arc(mx, my, MEMBER_RADIUS, 0, Math.PI * 2);
            ctx.fill();

            // Member outline
            ctx.strokeStyle = '#ffffff';
            ctx.lineWidth = 1;
            ctx.stroke();

            // Role label
            ctx.fillStyle = '#cccccc';
            ctx.font = '9px monospace';
            ctx.textAlign = 'center';
            ctx.fillText(member.role || 'unit', mx, my + MEMBER_RADIUS + 12);

            // Asset type icon
            const icon = member.asset_type === 'drone' ? 'D' :
                         member.asset_type === 'turret' ? 'T' : 'R';
            ctx.fillStyle = '#000000';
            ctx.font = 'bold 8px monospace';
            ctx.fillText(icon, mx, my + 3);
        });

        // Draw waypoints
        const waypoints = swarm.waypoints || [];
        if (waypoints.length > 0) {
            ctx.strokeStyle = '#fcee0a';
            ctx.lineWidth = 1;
            ctx.setLineDash([4, 4]);
            ctx.beginPath();
            ctx.moveTo(cx, cy);
            waypoints.forEach(wp => {
                const wpx = cx + (wp[0] - swarm.center_x) * scale;
                const wpy = cy - (wp[1] - swarm.center_y) * scale;
                ctx.lineTo(wpx, wpy);
            });
            ctx.stroke();
            ctx.setLineDash([]);

            // Waypoint markers
            waypoints.forEach((wp, i) => {
                const wpx = cx + (wp[0] - swarm.center_x) * scale;
                const wpy = cy - (wp[1] - swarm.center_y) * scale;
                const isCurrent = i === swarm.current_waypoint_idx;
                ctx.fillStyle = isCurrent ? '#fcee0a' : '#666';
                ctx.beginPath();
                ctx.arc(wpx, wpy, 3, 0, Math.PI * 2);
                ctx.fill();
            });
        }
    }

    function renderCanvas() {
        if (!ctx || !canvasEl) return;

        ctx.clearRect(0, 0, canvasEl.width, canvasEl.height);

        // Background grid
        ctx.strokeStyle = '#1a1a2e';
        ctx.lineWidth = 1;
        for (let x = 0; x < canvasEl.width; x += 20) {
            ctx.beginPath();
            ctx.moveTo(x, 0);
            ctx.lineTo(x, canvasEl.height);
            ctx.stroke();
        }
        for (let y = 0; y < canvasEl.height; y += 20) {
            ctx.beginPath();
            ctx.moveTo(0, y);
            ctx.lineTo(canvasEl.width, y);
            ctx.stroke();
        }

        // Draw selected swarm or first swarm
        const swarm = selectedSwarmId
            ? swarms.find(s => s.swarm_id === selectedSwarmId)
            : swarms[0];

        if (swarm) {
            drawFormation(swarm);
        } else {
            ctx.fillStyle = '#666';
            ctx.font = '12px monospace';
            ctx.textAlign = 'center';
            ctx.fillText('No swarms configured', canvasEl.width / 2, canvasEl.height / 2);
        }
    }

    function buildSwarmList() {
        const listEl = panelEl?.querySelector('.swarm-list');
        if (!listEl) return;

        if (swarms.length === 0) {
            listEl.innerHTML = '<div class="swarm-empty">No swarms. Create one to begin.</div>';
            return;
        }

        listEl.innerHTML = swarms.map(s => `
            <div class="swarm-item ${s.swarm_id === selectedSwarmId ? 'selected' : ''}"
                 data-swarm-id="${s.swarm_id}">
                <div class="swarm-item-header">
                    <span class="swarm-name">${s.name}</span>
                    <span class="swarm-formation" style="color: ${FORMATION_COLORS[s.formation_type] || '#00f0ff'}">
                        ${s.formation_type.toUpperCase()}
                    </span>
                </div>
                <div class="swarm-item-detail">
                    ${s.active_members}/${s.member_count} units | CMD: ${s.command}
                </div>
            </div>
        `).join('');

        listEl.querySelectorAll('.swarm-item').forEach(el => {
            el.addEventListener('click', () => {
                selectedSwarmId = el.dataset.swarmId;
                render();
            });
        });
    }

    function render() {
        if (!panelEl) return;
        buildSwarmList();
        renderCanvas();
    }

    function createPanel(container) {
        panelEl = document.createElement('div');
        panelEl.className = 'panel swarm-coordination-panel';
        panelEl.innerHTML = `
            <div class="panel-header">
                <span class="panel-title">SWARM COORDINATION</span>
                <div class="panel-actions">
                    <button class="btn-small btn-create-swarm" title="Create Swarm">+ NEW</button>
                    <button class="btn-small btn-refresh-swarm" title="Refresh">REFRESH</button>
                </div>
            </div>
            <div class="panel-body" style="display: flex; flex-direction: column; gap: 8px;">
                <div class="swarm-list" style="max-height: 120px; overflow-y: auto;"></div>
                <canvas class="swarm-canvas" width="400" height="250"
                    style="background: #0a0a0f; border: 1px solid #1a1a2e; border-radius: 4px;"></canvas>
                <div class="swarm-controls" style="display: flex; gap: 4px; flex-wrap: wrap;">
                    <button class="btn-small btn-cmd" data-cmd="hold">HOLD</button>
                    <button class="btn-small btn-cmd" data-cmd="advance">ADVANCE</button>
                    <button class="btn-small btn-cmd" data-cmd="patrol">PATROL</button>
                    <button class="btn-small btn-cmd" data-cmd="spread">SPREAD</button>
                    <button class="btn-small btn-cmd" data-cmd="converge">CONVERGE</button>
                    <select class="formation-select" style="background: #12121a; color: #00f0ff; border: 1px solid #1a1a2e; padding: 2px 4px; font-size: 11px;">
                        <option value="line">LINE</option>
                        <option value="wedge">WEDGE</option>
                        <option value="circle">CIRCLE</option>
                        <option value="diamond">DIAMOND</option>
                        <option value="column">COLUMN</option>
                    </select>
                </div>
            </div>
        `;

        canvasEl = panelEl.querySelector('.swarm-canvas');
        ctx = canvasEl.getContext('2d');

        // Event handlers
        panelEl.querySelector('.btn-create-swarm').addEventListener('click', () => {
            const name = prompt('Swarm name:', 'Alpha Squad');
            if (name) createSwarm(name, 'line', 5.0);
        });

        panelEl.querySelector('.btn-refresh-swarm').addEventListener('click', () => {
            fetchSwarms().then(render);
        });

        panelEl.querySelectorAll('.btn-cmd').forEach(btn => {
            btn.addEventListener('click', () => {
                if (selectedSwarmId) {
                    issueCommand(selectedSwarmId, btn.dataset.cmd);
                }
            });
        });

        panelEl.querySelector('.formation-select').addEventListener('change', (e) => {
            if (selectedSwarmId) {
                issueCommand(selectedSwarmId, null, null, e.target.value);
            }
        });

        container.appendChild(panelEl);

        // Initial fetch and start animation
        fetchSwarms().then(() => {
            if (swarms.length > 0 && !selectedSwarmId) {
                selectedSwarmId = swarms[0].swarm_id;
            }
            render();
        });

        // Auto-refresh every 2s
        setInterval(() => {
            fetchSwarms().then(render);
        }, 2000);
    }

    function destroy() {
        if (animationFrame) {
            cancelAnimationFrame(animationFrame);
            animationFrame = null;
        }
        if (panelEl && panelEl.parentNode) {
            panelEl.parentNode.removeChild(panelEl);
        }
        panelEl = null;
        canvasEl = null;
        ctx = null;
    }

    // Map overlay: render swarm formations on the tactical map
    function renderMapOverlay(mapCtx, mapCanvas, worldToScreen) {
        if (!swarms.length) return;

        swarms.forEach(swarm => {
            const color = FORMATION_COLORS[swarm.formation_type] || '#00f0ff';
            const members = swarm.members || [];
            if (!members.length) return;

            // Draw formation connections
            mapCtx.strokeStyle = color;
            mapCtx.lineWidth = 1;
            mapCtx.globalAlpha = 0.4;

            if (members.length > 1) {
                mapCtx.beginPath();
                members.forEach((m, i) => {
                    const pos = worldToScreen(m.position_x, m.position_y);
                    if (i === 0) mapCtx.moveTo(pos.x, pos.y);
                    else mapCtx.lineTo(pos.x, pos.y);
                });
                if (swarm.formation_type === 'circle') {
                    mapCtx.closePath();
                }
                mapCtx.stroke();
            }

            mapCtx.globalAlpha = 1.0;

            // Draw member dots on map
            members.forEach(m => {
                const pos = worldToScreen(m.position_x, m.position_y);
                mapCtx.fillStyle = m.status === 'active' ? color : '#666';
                mapCtx.beginPath();
                mapCtx.arc(pos.x, pos.y, 4, 0, Math.PI * 2);
                mapCtx.fill();
            });

            // Draw center marker
            const centerPos = worldToScreen(swarm.center_x, swarm.center_y);
            mapCtx.strokeStyle = '#ffffff';
            mapCtx.lineWidth = 2;
            mapCtx.beginPath();
            mapCtx.arc(centerPos.x, centerPos.y, 8, 0, Math.PI * 2);
            mapCtx.stroke();

            // Swarm label
            mapCtx.fillStyle = color;
            mapCtx.font = '10px monospace';
            mapCtx.textAlign = 'center';
            mapCtx.fillText(swarm.name, centerPos.x, centerPos.y - 14);
        });
    }

    return {
        createPanel,
        destroy,
        renderMapOverlay,
        fetchSwarms,
        createSwarm,
        issueCommand,
        addMember,
        getSwarms: () => swarms,
    };
})();

if (typeof window !== 'undefined') {
    window.SwarmCoordination = SwarmCoordination;
}
