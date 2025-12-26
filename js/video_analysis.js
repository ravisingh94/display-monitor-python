export function initVideoAnalysisMode(container) {
    renderUI(container);
}

let currentReport = [];
let videoElement = null;

// Toast notification helper
function showWarningToast(message) {
    // Create toast container if it doesn't exist
    let toastContainer = document.getElementById('toast-container');
    if (!toastContainer) {
        toastContainer = document.createElement('div');
        toastContainer.id = 'toast-container';
        toastContainer.style.cssText = `
            position: fixed;
            top: 20px;
            right: 20px;
            z-index: 10000;
            display: flex;
            flex-direction: column;
            gap: 10px;
        `;
        document.body.appendChild(toastContainer);
    }

    // Create toast element
    const toast = document.createElement('div');
    toast.style.cssText = `
        background: #ff9800;
        color: #000;
        padding: 1rem 1.5rem;
        border-radius: 8px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.3);
        max-width: 400px;
        animation: slideIn 0.3s ease-out;
        font-weight: 500;
        display: flex;
        align-items: center;
        gap: 0.5rem;
    `;

    toast.innerHTML = `
        <span style="font-size: 1.2rem;">⚠️</span>
        <span>${message}</span>
    `;

    // Add animation
    const style = document.createElement('style');
    style.textContent = `
        @keyframes slideIn {
            from {
                transform: translateX(100%);
                opacity: 0;
            }
            to {
                transform: translateX(0);
                opacity: 1;
            }
        }
        @keyframes slideOut {
            from {
                transform: translateX(0);
                opacity: 1;
            }
            to {
                transform: translateX(100%);
                opacity: 0;
            }
        }
    `;
    if (!document.getElementById('toast-styles')) {
        style.id = 'toast-styles';
        document.head.appendChild(style);
    }

    toastContainer.appendChild(toast);

    // Auto-remove after 8 seconds
    setTimeout(() => {
        toast.style.animation = 'slideOut 0.3s ease-in';
        setTimeout(() => {
            toast.remove();
            if (toastContainer.children.length === 0) {
                toastContainer.remove();
            }
        }, 300);
    }, 8000);
}


function renderUI(container) {
    container.innerHTML = `
        <div class="monitor-view">
             <header class="monitor-toolbar">
                <div style="display:flex; align-items:center; gap:var(--space-sm); margin-right:auto;">
                    <span style="font-size:1.2rem;">🎥</span>
                    <h2 style="font-size:1.1rem; font-weight:600;">Video Analysis</h2>
                </div>
                
                <button class="btn btn-primary btn-sm" onclick="location.reload()">Back to Home</button>
            </header>

            <main class="monitor-content" style="padding: 2rem; display: flex; flex-direction: column; align-items: center; gap: 2rem;">
                
                <div class="card" id="upload-card" style="width: 100%; max-width: 600px; padding: 2rem; text-align: center;">
                    <h3>Upload Video for Analysis</h3>
                    <p style="color: var(--text-muted); margin-bottom: 2rem;">
                        Select a video file from your local computer to analyze for visual glitches. 
                        The analysis may take some time depending on video length.
                    </p>
                    
                    <div style="display: flex; gap: 1rem; justify-content: center; align-items: center;">
                        <input type="file" id="video-upload-input" accept="video/*" style="display: none;" onchange="document.getElementById('file-name-display').innerText = this.files[0] ? this.files[0].name : 'No file chosen'">
                        <button class="btn btn-secondary" onclick="document.getElementById('video-upload-input').click()">Choose File</button>
                        <span id="file-name-display" style="color: var(--text-muted);">No file chosen</span>
                    </div>

                    <div style="margin-top: 2rem;">
                        <button id="btn-start-analysis" class="btn btn-primary" onclick="window.startAnalysis()">Start Analysis</button>
                    </div>
                </div>

                <div id="analysis-status" style="display: none; width: 100%; max-width: 1200px;">
                    <!-- Loading State -->
                    <div id="loading-state" style="text-align: center; padding: 3rem;">
                        <div class="spinner" style="margin: 0 auto 1rem; border: 4px solid var(--surface-2); border-top: 4px solid var(--primary); border-radius: 50%; width: 40px; height: 40px; animation: spin 1s linear infinite;"></div>
                        <h4>Analyzing Video...</h4>
                        <p style="color: var(--text-muted);">This allows for frame-by-frame inspection. Please wait.</p>
                        <style>@keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }</style>
                    </div>

                    <!-- Results State: Split View -->
                    <div id="results-state" style="display: none; height: 80vh;">
                         <div style="display: grid; grid-template-columns: 2fr 1fr; gap: 2rem; height: 100%;">
                            
                            <!-- Left: Video Player & Controls -->
                            <div style="display: flex; flex-direction: column; gap: 1rem;">
                                <div class="video-container" style="background: #000; border-radius: 8px; overflow: hidden; position: relative; flex-grow: 1; display: flex; align-items: center; justify-content: center;">
                                    <video id="analysis-video" style="max-width: 100%; max-height: 100%;" controls playsinline></video>
                                    
                                    <!-- Live Overlay Badge -->
                                    <div id="live-overlay" style="position: absolute; top: 1rem; right: 1rem; background: rgba(0,0,0,0.7); padding: 0.5rem 1rem; border-radius: 4px; display: flex; align-items: center; gap: 0.5rem; backdrop-filter: blur(4px);">
                                        <div id="live-dot" style="width: 10px; height: 10px; border-radius: 50%; background: #444;"></div>
                                        <span id="live-status-text" style="font-weight: 600; color: #fff;">READY</span>
                                    </div>
                                    
                                    <!-- GPU Status Badge -->
                                    <div id="gpu-status-badge" style="position: absolute; top: 1rem; left: 1rem; background: rgba(0,0,0,0.7); padding: 0.5rem 1rem; border-radius: 4px; backdrop-filter: blur(4px); display: none;">
                                        <div style="display: flex; align-items: center; gap: 0.5rem;">
                                            <span id="gpu-icon" style="font-size: 1rem;">🖥️</span>
                                            <span id="gpu-status-text" style="font-weight: 600; font-size: 0.85rem; color: #fff;"></span>
                                        </div>
                                    </div>
                                </div>
                                
                                <!-- Playback Controls -->
                                <div class="card" style="padding: 1rem; display: flex; align-items: center; justify-content: space-between;">
                                    <div style="display: flex; gap: 0.5rem;">
                                        <button class="btn btn-secondary btn-sm" onclick="window.seekVideo(-5)">-5s</button>
                                        <button class="btn btn-secondary btn-sm" onclick="window.seekVideo(-1)">-1s</button>
                                        <button class="btn btn-secondary btn-sm" onclick="window.frameStep(-1)">❮ Frame</button>
                                        <button class="btn btn-primary btn-sm" id="btn-play-pause" onclick="window.togglePlay()">Play</button>
                                        <button class="btn btn-secondary btn-sm" onclick="window.frameStep(1)">Frame ❯</button>
                                        <button class="btn btn-secondary btn-sm" onclick="window.seekVideo(1)">+1s</button>
                                        <button class="btn btn-secondary btn-sm" onclick="window.seekVideo(5)">+5s</button>
                                    </div>
                                    <div style="display: flex; align-items: center; gap: 0.5rem;">
                                        <span style="font-size: 0.9rem; color: var(--text-muted);">Speed:</span>
                                        <select id="playback-speed" style="padding: 4px; border-radius: 4px; background: var(--surface-3); color: var(--text-main); border: 1px solid var(--border-subtle);" onchange="window.setSpeed(this.value)">
                                            <option value="0.25">0.25x</option>
                                            <option value="0.5">0.5x</option>
                                            <option value="1" selected>1.0x</option>
                                            <option value="1.5">1.5x</option>
                                            <option value="2">2.0x</option>
                                        </select>
                                    </div>
                                </div>
                            </div>

                            <!-- Right: Glitch Timeline/List -->
                            <div class="card" style="display: flex; flex-direction: column; overflow: hidden;">
                                <h3 style="padding: 1rem; border-bottom: 1px solid var(--border-subtle);">Detected Glitches</h3>
                                <div class="table-container" style="overflow-y: auto; flex-grow: 1;">
                                    <table style="width: 100%; border-collapse: collapse; text-align: left;">
                                        <thead style="background: var(--surface-2); position: sticky; top: 0;">
                                            <tr>
                                                <th style="padding: 0.75rem;">Time</th>
                                                <th style="padding: 0.75rem;">Severity</th>
                                                <th style="padding: 0.75rem;">Type</th>
                                            </tr>
                                        </thead>
                                        <tbody id="results-table-body">
                                            <!-- Rows injected here -->
                                        </tbody>
                                    </table>
                                </div>
                            </div>

                         </div>
                    </div>
                    
                    <!-- Error State -->
                    <div id="error-state" style="display: none; padding: 2rem; background: #3f1515; border: 1px solid #7f2a2a; border-radius: 8px; color: #ffcccc; text-align: center;">
                         <h4 id="error-message">Analysis Failed</h4>
                    </div>

                </div>

            </main>
        </div>
    `;

    // Bind functions
    window.startAnalysis = handleAnalysis;
    window.togglePlay = togglePlay;
    window.seekVideo = seekVideo;
    window.frameStep = frameStep;
    window.setSpeed = setSpeed;
}

let eventSource = null;

async function handleAnalysis() {
    const fileInput = document.getElementById('video-upload-input');
    const statusDiv = document.getElementById('analysis-status');
    const loadingDiv = document.getElementById('loading-state');
    const resultsDiv = document.getElementById('results-state');
    const errorDiv = document.getElementById('error-state');
    const uploadCard = document.getElementById('upload-card');

    if (!fileInput.files || fileInput.files.length === 0) {
        alert("Please select a video file first.");
        return;
    }

    const file = fileInput.files[0];
    const formData = new FormData();
    formData.append('video', file);

    // UI Updates - Show loading briefly
    uploadCard.style.display = 'none';
    statusDiv.style.display = 'block';
    loadingDiv.style.display = 'block';
    resultsDiv.style.display = 'none';
    errorDiv.style.display = 'none';

    // Update loading message for upload
    loadingDiv.querySelector('h4').innerText = 'Uploading Video...';
    loadingDiv.querySelector('p').innerText = 'Please wait while we prepare your video.';

    try {
        const response = await fetch('/api/analyze/video', {
            method: 'POST',
            body: formData
        });

        if (!response.ok) {
            const errText = await response.text();
            throw new Error(`Server Error: ${response.status} - ${errText}`);
        }

        const data = await response.json();

        if (data.status === 'uploaded') {
            // Setup Video Player immediately
            videoElement = document.getElementById('analysis-video');
            videoElement.src = data.video_url;

            // Setup Listeners
            videoElement.addEventListener('timeupdate', onTimeUpdate);
            videoElement.addEventListener('play', () => updatePlayBtn(true));
            videoElement.addEventListener('pause', () => updatePlayBtn(false));

            // Show video player
            loadingDiv.style.display = 'none';
            resultsDiv.style.display = 'block';

            // Update live status to "ANALYZING..."
            updateLiveStatus('analyzing', 'ANALYZING...');

            // Start SSE connection for live results
            subscribeToAnalysis(data.session_id);
        } else {
            throw new Error(data.error || 'Unknown error occurred');
        }

    } catch (error) {
        console.error("Analysis failed:", error);
        loadingDiv.style.display = 'none';
        errorDiv.style.display = 'block';
        document.getElementById('error-message').innerText = error.message;
        uploadCard.style.display = 'block'; // Allow retry
    }
}

function subscribeToAnalysis(sessionId) {
    // Close existing connection if any
    if (eventSource) {
        eventSource.close();
    }

    eventSource = new EventSource(`/api/analyze/stream/${sessionId}`);

    eventSource.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);

            if (data.error) {
                console.error('Analysis error:', data.error);
                updateLiveStatus('error', 'ERROR');
                eventSource.close();
                return;
            }

            if (data.type === 'gpu_status') {
                console.log('GPU status:', data.message);
                showGPUStatus(data.message, data.available);
            } else if (data.type === 'warning') {
                console.warn('Analysis warning:', data.message);
                showGPUStatus(data.message, false);
            } else if (data.type === 'progress') {
                updateLiveStatus('analyzing', `ANALYZING... (${data.second}s)`);
            } else if (data.type === 'complete') {
                // Analysis complete
                updateLiveStatus('complete', 'COMPLETE');
                eventSource.close();
                console.log(`Analysis complete. Total ${data.total_seconds} seconds processed.`);
            } else if (data.second !== undefined) {
                // New glitch detected
                addGlitchRow(data);
                currentReport.push(data);
            }
        } catch (e) {
            console.error('Failed to parse SSE event:', e);
        }
    };

    eventSource.onerror = (error) => {
        console.error('SSE connection error:', error);
        eventSource.close();
        updateLiveStatus('error', 'CONNECTION ERROR');
    };
}

function updateLiveStatus(state, text) {
    const dot = document.getElementById('live-dot');
    const statusText = document.getElementById('live-status-text');

    statusText.innerText = text;

    if (state === 'analyzing') {
        dot.style.background = '#ffad33';  // Orange
        dot.style.boxShadow = '0 0 8px #ffad33';
    } else if (state === 'complete') {
        dot.style.background = '#33cc33';  // Green
        dot.style.boxShadow = '0 0 8px #33cc33';
    } else if (state === 'error') {
        dot.style.background = '#ff4d4d';  // Red
        dot.style.boxShadow = '0 0 10px #ff4d4d';
    } else {
        dot.style.background = '#444';
        dot.style.boxShadow = 'none';
    }
}

function showGPUStatus(message, isAvailable) {
    const badge = document.getElementById('gpu-status-badge');
    const icon = document.getElementById('gpu-icon');
    const text = document.getElementById('gpu-status-text');

    if (!badge) return;

    badge.style.display = 'block';

    if (isAvailable) {
        icon.innerText = '⚡';
        text.innerText = 'GPU Accelerated';
        text.style.color = '#33cc33';  // Green
    } else {
        icon.innerText = '⚠️';
        text.innerText = 'CPU Only (Slower)';
        text.style.color = '#ffad33';  // Orange
    }
}

function addGlitchRow(data) {
    const tbody = document.getElementById('results-table-body');

    // Check if tbody is empty (first result)
    if (tbody.children.length === 1 && tbody.children[0].cells.length === 1) {
        // Remove "No glitches" placeholder
        tbody.innerHTML = '';
    }

    let riskColor = 'var(--text-main)';
    if (data.severity === 'HIGH') riskColor = '#ff4d4d';
    if (data.severity === 'MEDIUM') riskColor = '#ffad33';
    if (data.severity === 'LOW') riskColor = '#33cc33';

    const row = document.createElement('tr');
    row.id = `row-sec-${data.second}`;
    row.className = 'result-row';
    row.style.cursor = 'pointer';
    row.style.borderBottom = '1px solid var(--border-subtle)';
    row.style.transition = 'background 0.1s';
    row.onclick = () => window.seekToAbsolute(data.second);

    row.innerHTML = `
        <td style="padding: 0.75rem; font-family: 'JetBrains Mono', monospace;">${formatTime(data.second)}</td>
        <td style="padding: 0.75rem;"><span style="color: ${riskColor}; font-weight: 600;">${data.severity}</span></td>
        <td style="padding: 0.75rem; font-size: 0.9rem; color: var(--text-muted);">${data.types.join(', ')}</td>
    `;

    tbody.appendChild(row);

    // Auto-scroll to bottom if user hasn't scrolled up
    const tableContainer = tbody.closest('.table-container');
    if (tableContainer) {
        const isNearBottom = tableContainer.scrollTop + tableContainer.clientHeight >= tableContainer.scrollHeight - 50;
        if (isNearBottom) {
            row.scrollIntoView({ behavior: 'smooth', block: 'end' });
        }
    }
}


function renderResults(report) {
    const tbody = document.getElementById('results-table-body');

    if (!report || report.length === 0) {
        tbody.innerHTML = `<tr><td colspan="3" style="padding: 2rem; text-align: center; color: var(--text-muted);">No glitches detected yet. Analysis in progress...</td></tr>`;
        return;
    }

    tbody.innerHTML = report.map((row, index) => {
        let riskColor = 'var(--text-main)';
        if (row.severity === 'HIGH') riskColor = '#ff4d4d'; // Red
        if (row.severity === 'MEDIUM') riskColor = '#ffad33'; // Orange
        if (row.severity === 'LOW') riskColor = '#33cc33'; // Green

        return `
            <tr id="row-sec-${row.second}" class="result-row" onclick="window.seekToAbsolute(${row.second})" style="cursor: pointer; border-bottom: 1px solid var(--border-subtle); transition: background 0.1s;">
                <td style="padding: 0.75rem; font-family: 'JetBrains Mono', monospace;">${formatTime(row.second)}</td>
                <td style="padding: 0.75rem;"><span style="color: ${riskColor}; font-weight: 600;">${row.severity}</span></td>
                <td style="padding: 0.75rem; font-size: 0.9rem; color: var(--text-muted);">${row.types.join(', ')}</td>
            </tr>
        `;
    }).join('');

    // Expose seeker
    window.seekToAbsolute = (sec) => {
        if (videoElement) {
            videoElement.currentTime = sec;
            videoElement.play();
        }
    };
}

function onTimeUpdate() {
    if (!videoElement) return;
    const currentTime = videoElement.currentTime;
    const currentSec = Math.floor(currentTime);

    // Find matching report entry
    const entry = currentReport.find(r => r.second === currentSec);

    updateOverlay(entry);
    highlightRow(currentSec);
}

function updateOverlay(entry) {
    const dot = document.getElementById('live-dot');
    const text = document.getElementById('live-status-text');

    if (entry) {
        text.innerText = `${entry.severity} | ${entry.types.join(', ')}`;
        if (entry.severity === 'HIGH') {
            dot.style.background = '#ff4d4d';
            dot.style.boxShadow = '0 0 10px #ff4d4d';
        } else if (entry.severity === 'MEDIUM') {
            dot.style.background = '#ffad33';
            dot.style.boxShadow = '0 0 8px #ffad33';
        } else {
            dot.style.background = '#33cc33';
            dot.style.boxShadow = 'none';
        }
    } else {
        text.innerText = "NORMAL";
        dot.style.background = '#444'; // inactive/normal
        dot.style.boxShadow = 'none';
    }
}

function highlightRow(sec) {
    // Remove old highlights
    document.querySelectorAll('.result-row.active-row').forEach(el => {
        el.classList.remove('active-row');
        el.style.background = 'transparent';
    });

    // Add new
    const row = document.getElementById(`row-sec-${sec}`);
    if (row) {
        row.classList.add('active-row');
        row.style.background = 'var(--surface-3)';
        row.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
}

// Playback Controls
function togglePlay() {
    if (!videoElement) return;
    if (videoElement.paused) videoElement.play();
    else videoElement.pause();
}

function updatePlayBtn(isPlaying) {
    const btn = document.getElementById('btn-play-pause');
    if (btn) btn.innerText = isPlaying ? "Pause" : "Play";
}

function seekVideo(offset) {
    if (videoElement) videoElement.currentTime += offset;
}

function frameStep(frames) {
    if (videoElement) {
        videoElement.pause(); // Step implies pause
        // Assume 30fps for simple step if not known, or usually 0.033s
        videoElement.currentTime += (frames * 0.033);
    }
}

function setSpeed(speed) {
    if (videoElement) videoElement.playbackRate = parseFloat(speed);
}

function formatTime(seconds) {
    const m = Math.floor(seconds / 60);
    const s = seconds % 60;
    return `${m}:${s.toString().padStart(2, '0')}`;
}
