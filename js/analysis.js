
/**
 * js/analysis.js
 * Analysis Dashboard for exploring stored sessions.
 */

let activeChart = null;
let currentSessionEvents = [];

export function initAnalysisMode(container) {
    container.innerHTML = `
        <div class="analysis-layout">
            <aside class="analysis-sidebar">
                <div class="sidebar-header">
                    <h2>Session Reports</h2>
                    <button class="btn btn-secondary btn-sm" id="btn-back-landing">Back</button>
                </div>
                <div class="session-list" id="session-list-container">
                    <div class="loading-placeholder">Loading sessions...</div>
                </div>
            </aside>
            <main class="analysis-main" id="analysis-content">
                <div class="empty-state">
                    <div class="icon">📊</div>
                    <h3>Select a session to begin analysis</h3>
                    <p>Comparison of glitches, OCR matches, and display statuses over recorded time.</p>
                </div>
            </main>
        </div>
    `;

    document.getElementById('btn-back-landing').onclick = () => {
        window.location.reload();
    };

    fetchSessions();
}

async function fetchSessions() {
    try {
        const res = await fetch('/api/sessions/list');
        const data = await res.json();
        renderSessionList(data.sessions);
    } catch (e) {
        console.error('Failed to fetch sessions:', e);
        document.getElementById('session-list-container').innerHTML = '<div class="error">Failed to load sessions</div>';
    }
}

function renderSessionList(sessions) {
    const container = document.getElementById('session-list-container');
    if (!sessions || sessions.length === 0) {
        container.innerHTML = '<div class="empty-msg">No recorded sessions found</div>';
        return;
    }

    container.innerHTML = sessions.map(s => `
        <div class="session-item" id="nav-${s.id}" onclick="loadSession('${s.id}')">
            <div class="session-title">${s.id}</div>
            <div class="session-meta">
                <span>📅 ${s.created}</span>
                ${s.has_video ? '<span>📹 Video</span>' : ''}
            </div>
        </div>
    `).join('');
}

window.loadSession = async function (id) {
    // UI feedback for selection
    document.querySelectorAll('.session-item').forEach(el => el.classList.remove('selected'));
    const activeItem = document.getElementById('nav-' + id);
    if (activeItem) activeItem.classList.add('selected');

    const main = document.getElementById('analysis-content');
    main.innerHTML = '<div class="loading-placeholder">Loading session data...</div>';

    try {
        const res = await fetch('/api/sessions/' + id + '/events');
        const data = await res.json();
        currentSessionEvents = data.events;
        renderAnalysisDashboard(id, data);
    } catch (e) {
        console.error('Error loading session:', e);
        main.innerHTML = '<div class="error">Error loading session data</div>';
    }
};

function renderAnalysisDashboard(id, data) {
    const main = document.getElementById('analysis-content');
    main.innerHTML = `
        <div class="dashboard-grid">
            <div class="header-card">
                <div class="title-group">
                    <h1 style="display:inline-block; margin-right:15px;">${id}</h1>
                    <span class="badge">Session Report</span>
                </div>
                <div class="action-group">
                     <a href="${data.video_url}" target="_blank" class="btn btn-secondary btn-sm">Download Video</a>
                </div>
            </div>

            <div class="top-row">
                <div class="video-card">
                    <video id="session-video" controls style="width:100%; height:100%;" 
                           src="${data.video_url}?t=${Date.now()}"
                           onloadedmetadata="console.log('Video metadata loaded')"
                           onerror="console.error('Video error:', this.error)">
                    </video>
                </div>
                <div class="stats-card" id="event-stats">
                    <!-- Stats summary injected here -->
                </div>
            </div>

            <div class="chart-card">
                <div class="card-header">
                    <h3>Event Timeline</h3>
                    <div class="chart-legend">
                        <span class="legend-item"><i class="dot glitch"></i> Glitch</span>
                        <span class="legend-item"><i class="dot ocr"></i> OCR Match</span>
                        <span class="legend-item"><i class="dot status"></i> Status Change</span>
                    </div>
                </div>
                <div class="canvas-wrapper" style="height:300px;">
                    <canvas id="timeline-chart"></canvas>
                </div>
            </div>

            <div class="log-card">
                <h3>Event Log</h3>
                <div class="log-table-wrapper" style="max-height:400px; overflow-y:auto;">
                    <table class="log-table" style="width:100%;">
                        <thead>
                            <tr>
                                <th>Timestamp</th>
                                <th>Display</th>
                                <th>Type</th>
                                <th>Message</th>
                            </tr>
                        </thead>
                        <tbody id="event-log-body"></tbody>
                    </table>
                </div>
            </div>
        </div>
    `;

    renderStats(data.events);
    renderLogTable(data.events);
    createTimelineChart(data.events);

    // Explicitly trigger load and handle play promise
    const video = document.getElementById('session-video');
    if (video) {
        console.log('[Analysis] Loading session video:', video.src);
        video.load();

        // Browsers often block autoplay, but since this is user-initiated (click list), it might work
        // or we just let the user hit play.
        video.onplay = () => console.log('[Analysis] Video started playing');
        video.onerror = (e) => {
            console.error('[Analysis] Video playback failed:', video.error);
            const msg = document.createElement('div');
            msg.className = 'video-error-overlay';
            msg.innerHTML = '<p>⚠️ This video uses an unsupported codec.</p>';
            video.parentElement.appendChild(msg);
        };
    }
}

function renderStats(events) {
    const stats = {
        glitches: events.filter(e => e.type === 'GLITCH_DETECTED').length,
        ocr: events.filter(e => e.type === 'OCR_NEGATIVE_MATCH').length,
        statusChanges: events.filter(e => e.type === 'STATUS_CHANGE').length,
    };

    const container = document.getElementById('event-stats');
    container.innerHTML = `
        <div class="stat-item">
            <div class="val">${stats.glitches}</div>
            <div class="lab">Glitches Detected</div>
        </div>
        <div class="stat-item">
            <div class="val">${stats.ocr}</div>
            <div class="lab">OCR Text Matches</div>
        </div>
        <div class="stat-item">
            <div class="val">${stats.statusChanges}</div>
            <div class="lab">Status Changes</div>
        </div>
    `;
}

function renderLogTable(events) {
    const body = document.getElementById('event-log-body');
    body.innerHTML = events.map(e => {
        const typeClass = e.type ? e.type.toLowerCase() : '';
        const display = e.display || '-';
        const tsShort = e.ts ? e.ts.split(' ')[1] : '';

        return `
            <tr class="event-row ${typeClass}" onclick="seekVideo('${e.ts}')">
                <td>${tsShort}</td>
                <td class="display-name">${display}</td>
                <td><span class="tag ${typeClass}">${e.type}</span></td>
                <td class="msg-col">${e.msg}</td>
            </tr>
        `;
    }).join('');
}

function createTimelineChart(events) {
    const canvas = document.getElementById('timeline-chart');
    if (!canvas) return;

    if (activeChart) activeChart.destroy();

    const startTimeStr = events[0].ts;
    const startTimeParsed = new Date(startTimeStr.replace(/-/g, '/')).getTime();

    const displays = [...new Set(events.map(e => e.display).filter(d => d))];
    if (displays.length === 0) displays.push('Session');

    const typeColors = {
        'GLITCH_DETECTED': '#ef4444',
        'OCR_NEGATIVE_MATCH': '#f59e0b',
        'STATUS_CHANGE': '#3b82f6',
        'OCR_DETECTED': '#10b981'
    };

    const dataPoints = events.map(e => {
        const t = new Date(e.ts.replace(/-/g, '/')).getTime();
        const relativeSeconds = (t - startTimeParsed) / 1000;

        return {
            x: relativeSeconds,
            y: displays.indexOf(e.display || 'Session'),
            type: e.type,
            msg: e.msg,
            ts: e.ts
        };
    }).filter(p => typeColors[p.type]);

    activeChart = new Chart(canvas, {
        type: 'scatter',
        data: {
            datasets: [{
                label: 'Events',
                data: dataPoints,
                pointBackgroundColor: (context) => {
                    const raw = context.raw;
                    return typeColors[raw ? raw.type : ''] || '#ccc';
                },
                pointRadius: 6,
                pointHoverRadius: 8
            }]
        },
        options: {
            maintainAspectRatio: false,
            scales: {
                x: {
                    title: { display: true, text: 'Seconds into Session', color: '#94a3b8' },
                    grid: { color: '#333' },
                    ticks: { color: '#94a3b8' }
                },
                y: {
                    ticks: {
                        callback: (value) => displays[value] || '',
                        color: '#94a3b8'
                    },
                    grid: { color: '#333' },
                    min: -0.5,
                    max: displays.length - 0.5
                }
            },
            plugins: {
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        label: (ctx) => {
                            const p = ctx.raw;
                            return ['[' + p.type + '] ' + p.ts, p.msg];
                        }
                    }
                }
            },
            onClick: (evt, elements) => {
                if (elements.length > 0) {
                    const index = elements[0].index;
                    const p = dataPoints[index];
                    seekVideo(p.ts);
                }
            }
        }
    });
}

window.seekVideo = function (timestamp) {
    const video = document.getElementById('session-video');
    if (!video || currentSessionEvents.length === 0) return;

    const startTs = new Date(currentSessionEvents[0].ts.replace(/-/g, '/')).getTime();
    const targetTs = new Date(timestamp.replace(/-/g, '/')).getTime();
    const offset = (targetTs - startTs) / 1000;

    video.currentTime = Math.max(0, offset);
    video.play().catch(err => {
        console.warn('[Analysis] Auto-play prevented or failed:', err);
    });
};
