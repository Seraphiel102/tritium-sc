// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.

/**
 * Map Time Slider — scrub through the last 24 hours of target positions.
 *
 * Renders a horizontal time slider at the bottom of the tactical map that
 * uses the temporal playback API to show target positions at each point
 * in time. The slider spans the available data range and updates the map
 * as the user drags through time.
 *
 * Usage:
 *   const slider = new TimeSlider(containerEl, { onSeek: (timestamp) => {...} });
 *   slider.init();
 */

class TimeSlider {
    constructor(container, options = {}) {
        this.container = container;
        this.onSeek = options.onSeek || (() => {});
        this.onPlayStateChange = options.onPlayStateChange || (() => {});

        // State
        this.rangeStart = 0;
        this.rangeEnd = 0;
        this.currentTime = 0;
        this.playing = false;
        this.playSpeed = 1.0;
        this.playTimer = null;
        this.snapshotCount = 0;

        // DOM elements (created in init)
        this.el = null;
        this.track = null;
        this.thumb = null;
        this.timeLabel = null;
        this.playBtn = null;
        this.speedLabel = null;

        this._dragging = false;
    }

    async init() {
        this._createDOM();
        this._bindEvents();
        await this.refresh();
    }

    _createDOM() {
        this.el = document.createElement('div');
        this.el.className = 'time-slider';
        this.el.innerHTML = `
            <div class="time-slider__controls">
                <button class="time-slider__play-btn" title="Play/Pause">
                    <span class="time-slider__play-icon">&#9654;</span>
                </button>
                <span class="time-slider__time-label">--:--</span>
                <div class="time-slider__track">
                    <div class="time-slider__fill"></div>
                    <div class="time-slider__thumb"></div>
                </div>
                <span class="time-slider__end-label">--:--</span>
                <button class="time-slider__speed-btn" title="Playback speed">1x</button>
            </div>
        `;

        // Style
        const style = document.createElement('style');
        style.textContent = `
            .time-slider {
                position: absolute;
                bottom: 8px;
                left: 50%;
                transform: translateX(-50%);
                width: calc(100% - 120px);
                max-width: 900px;
                background: rgba(10, 10, 15, 0.92);
                border: 1px solid #00f0ff33;
                border-radius: 6px;
                padding: 6px 12px;
                z-index: 200;
                user-select: none;
                backdrop-filter: blur(6px);
            }
            .time-slider__controls {
                display: flex;
                align-items: center;
                gap: 8px;
            }
            .time-slider__play-btn,
            .time-slider__speed-btn {
                background: rgba(0, 240, 255, 0.1);
                border: 1px solid #00f0ff44;
                color: #00f0ff;
                font-size: 12px;
                cursor: pointer;
                border-radius: 4px;
                padding: 4px 8px;
                min-width: 32px;
                line-height: 1;
            }
            .time-slider__play-btn:hover,
            .time-slider__speed-btn:hover {
                background: rgba(0, 240, 255, 0.2);
            }
            .time-slider__time-label,
            .time-slider__end-label {
                color: #00f0ff;
                font-family: 'Share Tech Mono', monospace;
                font-size: 11px;
                min-width: 44px;
                text-align: center;
            }
            .time-slider__track {
                flex: 1;
                height: 6px;
                background: #1a1a2e;
                border-radius: 3px;
                position: relative;
                cursor: pointer;
            }
            .time-slider__fill {
                position: absolute;
                left: 0;
                top: 0;
                height: 100%;
                background: linear-gradient(90deg, #00f0ff66, #00f0ff);
                border-radius: 3px;
                width: 0%;
                pointer-events: none;
            }
            .time-slider__thumb {
                position: absolute;
                top: 50%;
                left: 0%;
                transform: translate(-50%, -50%);
                width: 14px;
                height: 14px;
                background: #00f0ff;
                border-radius: 50%;
                box-shadow: 0 0 8px #00f0ff88;
                cursor: grab;
            }
            .time-slider__thumb:active {
                cursor: grabbing;
                box-shadow: 0 0 14px #00f0ff;
            }
        `;
        this.container.appendChild(style);
        this.container.appendChild(this.el);

        // Cache DOM refs
        this.track = this.el.querySelector('.time-slider__track');
        this.thumb = this.el.querySelector('.time-slider__thumb');
        this.fill = this.el.querySelector('.time-slider__fill');
        this.timeLabel = this.el.querySelector('.time-slider__time-label');
        this.endLabel = this.el.querySelector('.time-slider__end-label');
        this.playBtn = this.el.querySelector('.time-slider__play-btn');
        this.speedBtn = this.el.querySelector('.time-slider__speed-btn');
    }

    _bindEvents() {
        // Play button
        this.playBtn.addEventListener('click', () => this.togglePlay());

        // Speed button
        this.speedBtn.addEventListener('click', () => this._cycleSpeed());

        // Track click
        this.track.addEventListener('mousedown', (e) => this._onTrackDown(e));
        this.track.addEventListener('touchstart', (e) => this._onTrackDown(e), { passive: false });

        // Drag
        document.addEventListener('mousemove', (e) => this._onDrag(e));
        document.addEventListener('mouseup', () => this._onDragEnd());
        document.addEventListener('touchmove', (e) => this._onDrag(e), { passive: false });
        document.addEventListener('touchend', () => this._onDragEnd());
    }

    _onTrackDown(e) {
        e.preventDefault();
        this._dragging = true;
        this._seekFromEvent(e);
    }

    _onDrag(e) {
        if (!this._dragging) return;
        e.preventDefault();
        this._seekFromEvent(e);
    }

    _onDragEnd() {
        this._dragging = false;
    }

    _seekFromEvent(e) {
        const rect = this.track.getBoundingClientRect();
        const clientX = e.touches ? e.touches[0].clientX : e.clientX;
        let pct = (clientX - rect.left) / rect.width;
        pct = Math.max(0, Math.min(1, pct));

        const ts = this.rangeStart + pct * (this.rangeEnd - this.rangeStart);
        this.currentTime = ts;
        this._updateVisual(pct);
        this.onSeek(ts);
    }

    _updateVisual(pct) {
        const p = (pct * 100).toFixed(2);
        this.thumb.style.left = p + '%';
        this.fill.style.width = p + '%';
        this.timeLabel.textContent = this._formatTime(this.currentTime);
    }

    _formatTime(ts) {
        if (!ts) return '--:--';
        const d = new Date(ts * 1000);
        const h = d.getHours().toString().padStart(2, '0');
        const m = d.getMinutes().toString().padStart(2, '0');
        return h + ':' + m;
    }

    _cycleSpeed() {
        const speeds = [0.5, 1.0, 2.0, 5.0, 10.0];
        const idx = speeds.indexOf(this.playSpeed);
        this.playSpeed = speeds[(idx + 1) % speeds.length];
        this.speedBtn.textContent = this.playSpeed + 'x';
    }

    async refresh() {
        try {
            const resp = await fetch('/api/playback/range');
            if (!resp.ok) return;
            const data = await resp.json();
            this.rangeStart = data.start || 0;
            this.rangeEnd = data.end || 0;
            this.snapshotCount = data.snapshot_count || 0;
            this.currentTime = this.rangeEnd;

            if (this.rangeStart > 0) {
                this.timeLabel.textContent = this._formatTime(this.rangeStart);
                this.endLabel.textContent = this._formatTime(this.rangeEnd);
                this._updateVisual(1.0);
            }
        } catch (e) {
            // Playback API may not be available yet
        }
    }

    togglePlay() {
        if (this.playing) {
            this.stop();
        } else {
            this.play();
        }
    }

    async play() {
        if (this.rangeEnd <= this.rangeStart) return;

        this.playing = true;
        this.playBtn.querySelector('.time-slider__play-icon').innerHTML = '&#9646;&#9646;';
        this.onPlayStateChange(true);

        // Use SSE replay stream
        try {
            const start = this.currentTime || this.rangeStart;
            const url = `/api/playback/replay?start=${start}&end=${this.rangeEnd}&speed=${this.playSpeed}&max_count=500`;
            const evtSource = new EventSource(url);

            this._evtSource = evtSource;

            evtSource.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);
                    if (data.error) {
                        this.stop();
                        return;
                    }

                    this.currentTime = data.timestamp;
                    const pct = (this.currentTime - this.rangeStart) / (this.rangeEnd - this.rangeStart);
                    this._updateVisual(Math.max(0, Math.min(1, pct)));
                    this.onSeek(this.currentTime, data.targets);
                } catch (e) {
                    // Ignore parse errors
                }
            };

            evtSource.addEventListener('done', () => {
                this.stop();
            });

            evtSource.onerror = () => {
                this.stop();
            };
        } catch (e) {
            this.stop();
        }
    }

    stop() {
        this.playing = false;
        this.playBtn.querySelector('.time-slider__play-icon').innerHTML = '&#9654;';
        this.onPlayStateChange(false);

        if (this._evtSource) {
            this._evtSource.close();
            this._evtSource = null;
        }
    }

    destroy() {
        this.stop();
        if (this.el && this.el.parentNode) {
            this.el.parentNode.removeChild(this.el);
        }
    }
}

// Export for use in other modules
if (typeof window !== 'undefined') {
    window.TimeSlider = TimeSlider;
}
