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

    // Group displays by camera
    const groups = {};
    displays.forEach(d => {
        const camLabel = d.camera_name || d.camId || 'Unknown Camera';
        if (!groups[camLabel]) groups[camLabel] = [];
        groups[camLabel].push(d);
    });

    grid.innerHTML = Object.entries(groups).map(([camLabel, camDisplays]) => {
        return `
        <div class="camera-group">
            <div class="camera-group-header">
                <span class="icon">📹</span>
                <span class="name">${camLabel}</span>
                <span class="count">${camDisplays.length} Display${camDisplays.length > 1 ? 's' : ''}</span>
            </div>
            <div class="camera-grid">
                ${camDisplays.map(d => `
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
                            <img id="stream-${d.id}" src="" 
                                 style="width:100%; height:100%; object-fit:contain; display:block;"
                                 onerror="document.getElementById('err-${d.id}').style.display='block';">
                            
                            <div id="err-${d.id}" style="display:none; color:var(--text-muted); text-align:center; padding:2rem;">
                                No Signal
                            </div>
            
                            <div class="glitch-list" id="glitch-list-${d.id}"></div>
                        </div>
                        <div class="tile-footer">
                            <span>ID: ${d.id.slice(-6)}</span>
                            <span class="timestamp" id="time-${d.id}">--:--:--</span>
                        </div>
                    </div>
                `).join('')}
            </div>
        </div>
        `;
    }).join('');

    // Expose toggleMaximize globally since onclick uses it
    window.toggleMaximize = toggleMaximize;
}

function startPollingLoop() {
    isMonitoring = true;

    // Start Snapshot Polling (High FPS)
    async function snapshotPoll() {
        if (!isMonitoring) return; // Use isMonitoring for consistency with existing code

        try {
            const res = await fetch('/api/monitor/snapshot');
            const data = await res.json();

            // 1. Update Statuses/Metrics
            if (data.statuses) {
                data.statuses.forEach(d => {
                    updateDisplayStatusUI(d.id, d.status, d.metrics, d.timestamp);
                });
            }

            // 2. Update Frames (Base64)
            if (data.frames) {
                for (const [id, b64] of Object.entries(data.frames)) {
                    const img = document.getElementById(`stream-${id}`);
                    if (img) {
                        img.src = `data:image/jpeg;base64,${b64}`;
                        const err = document.getElementById(`err-${id}`);
                        if (err) err.style.display = 'none';
                    }
                }
            }
        } catch (e) {
            console.warn("Snapshot poll failed", e);
        }

        // Schedule next update
        if (isMonitoring) { // Use isMonitoring for consistency
            pollingIntervalId = setTimeout(snapshotPoll, 50); // ~20 FPS target
        }
    }

    snapshotPoll();
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

async function captureSnapshot() {
    const displays = window.appState.displays || [];
    if (displays.length === 0) {
        alert('No displays to capture');
        return;
    }

    // Check if html2canvas is loaded
    if (typeof html2canvas === 'undefined') {
        alert('Snapshot library not loaded. Please refresh the page and try again.');
        console.error('html2canvas is not defined');
        return;
    }

    const btn = document.getElementById('btn-snapshot');
    const originalText = btn.innerText;
    btn.innerText = 'Capturing...';
    btn.disabled = true;

    console.log('[Snapshot] Starting capture...');

    // Store original stream sources and styles to restore later
    const streamBackup = [];
    const styleBackup = [];

    try {
        // Get the monitor grid container
        const gridElement = document.getElementById('monitor-grid');
        if (!gridElement) {
            throw new Error('Monitor grid not found');
        }

        console.log('[Snapshot] Grid element found, displays:', displays.length);

        // Temporarily remove maximized state for full capture
        const wasMaximized = maximizedDisplayId;
        if (wasMaximized) {
            console.log('[Snapshot] Temporarily removing maximized state');
            toggleMaximize(wasMaximized);
        }

        // CRITICAL: Freeze MJPEG streams and preserve aspect ratio
        console.log('[Snapshot] Freezing MJPEG streams with natural aspect ratio...');
        for (const display of displays) {
            const img = document.getElementById(`stream-${display.id}`);
            if (img && img.complete && img.naturalWidth > 0) {
                // Store original src and style
                streamBackup.push({ id: display.id, src: img.src });
                styleBackup.push({
                    id: display.id,
                    width: img.style.width,
                    height: img.style.height,
                    objectFit: img.style.objectFit
                });

                // Create canvas and draw current frame
                const canvas = document.createElement('canvas');
                canvas.width = img.naturalWidth;
                canvas.height = img.naturalHeight;
                const ctx = canvas.getContext('2d');

                try {
                    ctx.drawImage(img, 0, 0);
                    // Replace stream with static image
                    img.src = canvas.toDataURL('image/png');

                    // IMPORTANT: Set image to use natural dimensions to preserve aspect ratio
                    img.style.width = 'auto';
                    img.style.height = 'auto';
                    img.style.maxWidth = '100%';
                    img.style.maxHeight = '100%';
                    img.style.objectFit = 'contain';

                    console.log(`[Snapshot] Froze stream for ${display.id} (${img.naturalWidth}x${img.naturalHeight})`);
                } catch (e) {
                    console.warn(`[Snapshot] Failed to freeze ${display.id}:`, e);
                }
            }
        }

        // Wait for frozen images to load and resize
        await new Promise(resolve => setTimeout(resolve, 200));

        // Add metadata overlay
        const overlay = document.createElement('div');
        overlay.id = 'snapshot-overlay';
        overlay.style.cssText = `
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            background: linear-gradient(to bottom, rgba(0,0,0,0.8), transparent);
            padding: 1rem;
            color: white;
            font-family: 'Inter', sans-serif;
            z-index: 1000;
            pointer-events: none;
        `;
        overlay.innerHTML = `
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <div>
                    <h3 style="margin: 0; font-size: 1.2rem;">Display Monitoring Dashboard</h3>
                    <p style="margin: 0.25rem 0 0 0; font-size: 0.9rem; opacity: 0.8;">${displays.length} Display${displays.length > 1 ? 's' : ''} • Backend Analysis Mode</p>
                </div>
                <div style="text-align: right;">
                    <p style="margin: 0; font-size: 0.9rem;">${new Date().toLocaleDateString()}</p>
                    <p style="margin: 0.25rem 0 0 0; font-size: 0.9rem; opacity: 0.8;">${new Date().toLocaleTimeString()}</p>
                </div>
            </div>
        `;

        gridElement.style.position = 'relative';
        gridElement.insertBefore(overlay, gridElement.firstChild);

        console.log('[Snapshot] Overlay added, waiting for render...');

        // Wait a bit for overlay to render
        await new Promise(resolve => setTimeout(resolve, 200));

        console.log('[Snapshot] Calling html2canvas...');

        // Capture using html2canvas - now with static images at natural aspect ratio
        const canvas = await html2canvas(gridElement, {
            backgroundColor: '#0a0a0f',
            scale: 2,
            logging: false,
            useCORS: false,
            allowTaint: true
        });

        console.log('[Snapshot] Canvas created:', canvas.width, 'x', canvas.height);

        // Remove overlay
        overlay.remove();

        // Restore MJPEG streams and original styles
        console.log('[Snapshot] Restoring MJPEG streams and styles...');
        for (const backup of streamBackup) {
            const img = document.getElementById(`stream-${backup.id}`);
            if (img) {
                img.src = backup.src;
            }
        }
        for (const style of styleBackup) {
            const img = document.getElementById(`stream-${style.id}`);
            if (img) {
                img.style.width = style.width;
                img.style.height = style.height;
                img.style.objectFit = style.objectFit;
                img.style.maxWidth = '';
                img.style.maxHeight = '';
            }
        }

        // Restore maximized state if needed
        if (wasMaximized) {
            console.log('[Snapshot] Restoring maximized state');
            toggleMaximize(wasMaximized);
        }

        console.log('[Snapshot] Converting to blob...');

        // Convert canvas to blob
        canvas.toBlob((blob) => {
            if (!blob) {
                throw new Error('Failed to create image blob');
            }

            console.log('[Snapshot] Blob created, size:', blob.size, 'bytes');

            // Create download link
            const url = URL.createObjectURL(blob);
            const link = document.createElement('a');
            const timestamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
            link.download = `monitor_snapshot_${timestamp}.png`;
            link.href = url;
            link.click();

            console.log('[Snapshot] Download triggered');

            // Cleanup
            URL.revokeObjectURL(url);

            // Success feedback
            btn.innerText = '✓ Captured!';
            setTimeout(() => {
                btn.innerText = originalText;
                btn.disabled = false;
            }, 2000);
        }, 'image/png');

    } catch (error) {
        console.error('[Snapshot] Capture failed:', error);
        console.error('[Snapshot] Error stack:', error.stack);

        // Restore streams and styles on error
        console.log('[Snapshot] Restoring streams and styles after error...');
        for (const backup of streamBackup) {
            const img = document.getElementById(`stream-${backup.id}`);
            if (img) {
                img.src = backup.src;
            }
        }
        for (const style of styleBackup) {
            const img = document.getElementById(`stream-${style.id}`);
            if (img) {
                img.style.width = style.width;
                img.style.height = style.height;
                img.style.objectFit = style.objectFit;
                img.style.maxWidth = '';
                img.style.maxHeight = '';
            }
        }

        alert('Failed to capture snapshot: ' + error.message + '\n\nCheck browser console for details.');
        btn.innerText = originalText;
        btn.disabled = false;

        // Remove overlay if it exists
        const overlay = document.getElementById('snapshot-overlay');
        if (overlay) overlay.remove();

        // Restore maximized state if needed
        if (maximizedDisplayId) {
            toggleMaximize(maximizedDisplayId);
        }
    }
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
