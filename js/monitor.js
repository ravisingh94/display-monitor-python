import { navigateTo } from './app.js';

let isMonitoring = false;
let pollingIntervalId = null;
let displayViewModes = {};
let maximizedDisplayId = null;

export function initMonitorMode(container) {
    stopMonitoring();
    renderUI(container);
    loadAndStartMonitoring();
}

function renderUI(container) {
    container.innerHTML = `
        <div class="monitor-view">
            <header class="monitor-toolbar">
                <div style="display:flex; align-items:center; gap:var(--space-sm); margin-right:auto;">
                    <span style="font-size:1.2rem;">📊</span>
                    <h2 style="font-size:1.1rem; font-weight:600;">Monitoring Dashboard (Backend Analysis)</h2>
                </div>
                
                <div style="display:flex; gap:var(--space-sm);">
                    <button class="btn btn-secondary btn-sm" id="btn-snapshot">Capture Snapshot</button>
                    <div style="width:1px; background:var(--border-subtle); margin:0 5px;"></div>
                    <button class="btn btn-danger btn-sm" id="btn-exit-monitor">Exit Monitor</button>
                </div>
            </header>

            <main class="monitor-content">
                <div class="display-grid" id="monitor-grid">
                    <div style="grid-column: 1 / -1; text-align:center; padding:5rem; color:var(--text-muted);">
                        <h3>Connecting to Server...</h3>
                    </div>
                </div>
            </main>

            <div id="system-error-banner" class="error-banner"></div>
        </div>
    `;

    document.getElementById('btn-snapshot').addEventListener('click', captureSnapshot);
    document.getElementById('btn-exit-monitor').addEventListener('click', () => {
        stopMonitoring();
        navigateTo('landing-view');
    });
}

async function loadAndStartMonitoring() {
    try {
        const response = await fetch('/api/config/load');
        const data = await response.json();
        const displays = data.displays || [];

        window.appState.displays = displays;

        if (displays.length === 0) {
            renderEmptyState();
            return;
        }

        renderGrid(displays);
        startPollingLoop();

    } catch (error) {
        console.error('Failed to load configuration:', error);
        showError('Failed to connect to backend: ' + error.message);
    }
}

function renderEmptyState() {
    const grid = document.getElementById('monitor-grid');
    grid.innerHTML = `
        <div style="grid-column: 1 / -1; text-align:center; padding:5rem; color:var(--text-muted);">
            <h3>No Displays Configured</h3>
            <p>Please go to Configuration Mode to define monitor regions.</p>
            <button class="btn btn-primary" style="margin-top:1rem;" id="btn-return-setup">Return to Setup</button>
        </div>
    `;
    document.getElementById('btn-return-setup').addEventListener('click', () => navigateTo('config-view'));
}

function renderGrid(displays) {
    const grid = document.getElementById('monitor-grid');

    grid.innerHTML = displays.map(d => {
        // Backend handles cropping/warping, so we just show the stream 
        // Aspect ratio is determined by the config w/h

        return `
        <div class="display-tile state-active" id="tile-${d.id}">
            <div class="tile-header">
                <span class="tile-title">${d.name}</span>
                <div style="display:flex; gap:4px;">
                    <button class="btn-view-toggle" id="btn-fit-${d.id}" onclick="window.toggleFit('${d.id}', event)" title="Fit/Fill">
                        ↔
                    </button>
                    <button class="btn-view-toggle" id="btn-max-${d.id}" onclick="window.toggleMaximize('${d.id}', event)" title="Maximize">
                        ⛶
                    </button>
                </div>
                <div class="status-badge badge-unknown" id="badge-${d.id}">
                    <span class="status-dot"></span>
                    <span class="status-text" id="status-text-${d.id}">CONNECTING</span>
                </div>
            </div>
            <div class="tile-body tile-body-fit" id="tile-body-${d.id}">
                <!-- MJPEG Stream Source -->
                <img id="stream-${d.id}" src="/video_feed/${d.id}" 
                     style="width:100%; height:100%; object-fit:contain; display:block;"
                     onerror="this.style.display='none'; document.getElementById('err-${d.id}').style.display='block';">
                
                <div id="err-${d.id}" style="display:none; color:var(--text-muted); text-align:center; padding:2rem;">
                    No Signal
                </div>

                <div class="glitch-list" id="glitch-list-${d.id}"></div>
            </div>
            <div class="tile-footer">
                <span>Cam: ${d.camId}</span>
                <span class="timestamp" id="time-${d.id}">--:--:--</span>
            </div>
        </div>
        `}).join('');

    // Expose toggleMaximize globally since onclick uses it
    window.toggleMaximize = toggleMaximize;
}

function startPollingLoop() {
    isMonitoring = true;

    const poll = async () => {
        if (!isMonitoring) return;

        try {
            const res = await fetch('/api/monitor/status');
            if (res.ok) {
                const statuses = await res.json();
                updateUI(statuses);
            }
        } catch (e) {
            console.warn("Status poll failed", e);
        }
    };

    // Poll every 500ms
    pollingIntervalId = setInterval(poll, 500);
    poll(); // Initial call
}

function updateUI(statuses) {
    statuses.forEach(data => {
        updateDisplayStatusUI(data.id, data.status, data.metrics, data.timestamp);
    });
}

function updateDisplayStatusUI(displayId, status, metrics = {}, timestampStr = null) {
    const badge = document.getElementById(`badge-${displayId}`);
    const text = document.getElementById(`status-text-${displayId}`);
    const glitchList = document.getElementById(`glitch-list-${displayId}`);
    const tile = document.getElementById(`tile-${displayId}`);

    if (!badge || !text) return;

    // Reset classes
    badge.className = 'status-badge';

    // Handle Glitch Override
    const isGlitch = metrics.glitch === true;

    if (isGlitch) {
        badge.classList.add('badge-glitch');
        text.innerText = `GLITCH: ${metrics.glitch_severity || 'DETECTED'}`;

        if (glitchList && metrics.glitch_type) {
            glitchList.innerHTML = metrics.glitch_type.map(type =>
                `<div class="glitch-item">${type}</div>`
            ).join('');
        }
    } else {
        const statusLower = (status || 'unknown').toLowerCase();
        badge.classList.add(`badge-${statusLower}`);
        text.innerText = status || 'UNKNOWN';
        if (glitchList) glitchList.innerHTML = '';
    }

    // OCR Alert
    if (metrics.ocr_detected) {
        if (metrics.ocr_pattern) {
            badge.classList.add('badge-ocr-alert');
            text.innerText = `⚠️ ${metrics.ocr_pattern}`;

            if (glitchList) {
                glitchList.innerHTML = `<div class="ocr-alert-text">Detected: "${metrics.ocr_text}"</div>`;
            }
            if (tile) tile.classList.add('tile-ocr-alert');
        }
    } else if (!isGlitch && status !== 'FROZEN' && status !== 'OFF') {
        if (tile) tile.classList.remove('tile-ocr-alert');
    }

    // Error styling on tile
    if (tile) {
        if (status === 'FROZEN' || status === 'OFF' || isGlitch || metrics.ocr_detected) {
            if (!metrics.ocr_detected) tile.classList.add('tile-error'); // Red border for errors
        } else {
            tile.classList.remove('tile-error');
        }
    }

    // Footer Metrics
    if (tile) {
        let footerMetrics = tile.querySelector('.footer-metrics');
        if (!footerMetrics) {
            footerMetrics = document.createElement('div');
            footerMetrics.className = 'footer-metrics';
            footerMetrics.style.fontSize = '0.7rem';
            footerMetrics.style.color = 'var(--text-muted)';
            footerMetrics.style.width = '100%';
            footerMetrics.style.marginTop = '4px';
            const footer = tile.querySelector('.tile-footer');
            if (footer) {
                footer.style.flexWrap = 'wrap';
                footer.appendChild(footerMetrics);
            }
        }

        const frz = metrics.frozen_counter !== undefined ? ` | Frz: ${metrics.frozen_counter}` : '';
        const diff = metrics.diff_score !== undefined ? ` | Diff: ${metrics.diff_score.toFixed(2)}` : '';
        footerMetrics.innerText = `L:${Math.round(metrics.brightness)} V:${Math.round(metrics.variance)}${diff}${frz}`;
    }

    // Timestamp
    const timeEl = document.getElementById(`time-${displayId}`);
    if (timeEl && timestampStr) {
        timeEl.innerText = new Date(timestampStr).toLocaleTimeString();
    }
}

function toggleMaximize(displayId, event) {
    if (event) event.stopPropagation();

    const tile = document.getElementById(`tile-${displayId}`);
    const btn = document.getElementById(`btn-max-${displayId}`);
    const isMaximized = tile.classList.contains('tile-maximized');

    if (isMaximized) {
        tile.classList.remove('tile-maximized');
        maximizedDisplayId = null;
        if (btn) btn.innerText = '⛶';
        document.body.style.overflow = '';
    } else {
        tile.classList.add('tile-maximized');
        maximizedDisplayId = displayId;
        if (btn) btn.innerText = '❐';
        document.body.style.overflow = 'hidden';
    }
}

function stopMonitoring() {
    isMonitoring = false;
    if (pollingIntervalId) {
        clearInterval(pollingIntervalId);
        pollingIntervalId = null;
    }
}

function captureSnapshot() {
    const displays = window.appState.displays || [];
    if (displays.length === 0) return;

    // Snapshot logic needs to draw Images to canvas
    // TODO: Implement cleaner snapshot for IMG tags if needed
    // For now simple alert as placeholder or reimplement
    alert("Snapshot feature requires update for backend mode.");
}

function showError(msg) {
    const banner = document.getElementById('system-error-banner');
    if (banner) {
        banner.innerText = msg;
        banner.style.display = 'flex';
        setTimeout(() => banner.style.display = 'none', 5000);
    }
}

function toggleFit(displayId, event) {
    if (event) event.stopPropagation();
    const img = document.getElementById(`stream-${displayId}`);
    const btn = document.getElementById(`btn-fit-${displayId}`);

    if (!img) return;

    // Default is 'contain' as per CSS
    if (img.style.objectFit === 'fill') {
        img.style.objectFit = 'contain';
        if (btn) btn.innerText = '↔';
        if (btn) btn.title = "Fit to Window";
    } else {
        img.style.objectFit = 'fill';
        if (btn) btn.innerText = '⇳';
        if (btn) btn.title = "Stretch to Fill";
    }
}

// Expose to window for onclick handlers
window.toggleMaximize = toggleMaximize;
window.toggleFit = toggleFit;
