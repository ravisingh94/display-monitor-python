import { navigateTo } from './app.js';

let currentCanvasImage = null;
let activeDisplayId = null;
let isDragging = false;
let isResizing = false;
let isDrawing = false;
let drawingDisplayId = null;
let dragStartX, dragStartY;
let activeCornerIndex = -1; // -1 if not resizing a corner
let originalCorners = []; // For reference during translation/resize

// View State
let viewMode = 'fit'; // 'fit' or 'native'
let isRotating = false;
let activeSideIndex = -1; // -1 if not dragging a side
let rotateStartAngle = 0;
let rotateStartValue = 0; // The rotation at mousedown
let displayCenter = { x: 0, y: 0 };
let undoStack = [];
let redoStack = [];
let visualScale = 1.0; // Visual zoom factor for config view

function saveState() {
    // Deep clone the current displays to avoid reference issues
    const state = JSON.parse(JSON.stringify(window.appState.displays));
    undoStack.push(state);
    if (undoStack.length > 50) undoStack.shift(); // Limit history
    redoStack = []; // Clear redo on new action
    updateUndoRedoButtons();
}

function undo() {
    if (undoStack.length === 0) return;
    const currentState = JSON.parse(JSON.stringify(window.appState.displays));
    redoStack.push(currentState);

    const prevState = undoStack.pop();
    window.appState.displays = prevState;

    renderOverlays();
    renderDisplayList();
    updateUndoRedoButtons();
}

function redo() {
    if (redoStack.length === 0) return;
    const currentState = JSON.parse(JSON.stringify(window.appState.displays));
    undoStack.push(currentState);

    const nextState = redoStack.pop();
    window.appState.displays = nextState;

    renderOverlays();
    renderDisplayList();
    updateUndoRedoButtons();
}

function updateUndoRedoButtons() {
    const btnUndo = document.getElementById('btn-undo');
    const btnRedo = document.getElementById('btn-redo');
    if (btnUndo) btnUndo.disabled = undoStack.length === 0;
    if (btnRedo) btnRedo.disabled = redoStack.length === 0;
}

export function initConfigMode(container) {
    // Reset state
    viewMode = 'fit';
    renderConfigUI(container);
    loadConfig().then(() => {
        fetchCameras();
    });
}

function stopActiveStream() {
    const video = document.getElementById('config-video-layer');
    if (video && video.srcObject) {
        video.srcObject.getTracks().forEach(t => t.stop());
        video.srcObject = null;
    }
}

async function loadConfig() {
    try {
        const response = await fetch('/api/config/load');
        const data = await response.json();
        const savedDisplays = Array.isArray(data) ? data : (data.displays || []);

        if (savedDisplays && Array.isArray(savedDisplays)) {
            // Ensure 4-corner format is available and values are numbers
            savedDisplays.forEach(display => {
                const parseNum = (val) => isNaN(parseFloat(val)) ? 0 : parseFloat(val);

                if (display.corners && display.corners.length === 4) {
                    display.corners.forEach(c => {
                        c.x = parseNum(c.x);
                        c.y = parseNum(c.y);
                    });
                } else {
                    const x = parseNum(display.x);
                    const y = parseNum(display.y);
                    const w = parseNum(display.w);
                    const h = parseNum(display.h);
                    display.corners = [
                        { x: x, y: y },
                        { x: x + w, y: y },
                        { x: x + w, y: y + h },
                        { x: x, y: y + h }
                    ];
                }
                display.x = parseNum(display.x);
                display.y = parseNum(display.y);
                display.w = parseNum(display.w);
                display.h = parseNum(display.h);
                display.rotation = parseInt(display.rotation) || 0;
            });
            window.appState.displays = savedDisplays;
        }
    } catch (error) {
        console.error('Failed to load config:', error);
    }
}

async function saveConfig() {
    try {
        const displaysToSave = window.appState.displays.map(d => {
            const camera = window.appState.cameras.find(c => c.id === d.camId);

            // Safeguard for displays added without corners initialized
            let corners = d.corners;
            if (!corners || corners.length !== 4) {
                corners = [
                    { x: d.x, y: d.y },
                    { x: d.x + d.w, y: d.y },
                    { x: d.x + d.w, y: d.y + d.h },
                    { x: d.x, y: d.y + d.h }
                ];
            }

            return {
                id: d.id,
                name: d.name,
                camId: d.camId,
                camera_name: camera ? camera.name : 'Unknown',
                hardware_id: d.hardware_id || (camera ? camera.hardware_id : null),
                corners: corners,
                x: Math.min(...corners.map(c => c.x)),
                y: Math.min(...corners.map(c => c.y)),
                w: Math.max(...corners.map(c => c.x)) - Math.min(...corners.map(c => c.x)),
                h: Math.max(...corners.map(c => c.y)) - Math.min(...corners.map(c => c.y)),
                rotation: d.rotation || 0,
                enablePerspective: d.enablePerspective || false
            };
        });

        const response = await fetch('/api/config/save', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(displaysToSave)
        });

        const result = await response.json();
        if (result.status === 'success') {
            console.log('Configuration saved successfully');
            return true;
        } else {
            throw new Error(result.error || 'Save failed');
        }
    } catch (error) {
        console.error('Failed to save config:', error);
        alert('Error saving configuration: ' + error.message);
        return false;
    }
}

async function fetchCameras() {
    const list = document.getElementById('camera-list');
    if (list) list.innerHTML = '<div style="padding:10px; color:var(--text-muted);">Discovering cameras...</div>';

    try {
        // 1. Fetch backend cameras (ground truth for monitoring)
        const resp = await fetch('/api/cameras');
        const hostCameras = await resp.json(); // [{id: '0', name: 'Host Camera 0'}, ...]

        // 2. Fetch browser cameras (for preview)
        let browserDevices = [];
        try {
            const stream = await navigator.mediaDevices.getUserMedia({ video: true });
            stream.getTracks().forEach(t => t.stop());
            const devices = await navigator.mediaDevices.enumerateDevices();
            browserDevices = devices.filter(d => d.kind === 'videoinput');
        } catch (e) {
            console.warn('Browser camera access denied/unavailable');
        }

        // 3. Populate appState.cameras with host devices
        window.appState.cameras = hostCameras.map((hc, index) => {
            let browserMatch = null;

            // Only use label-based matching - DO NOT use index as browser order is unstable
            // Try multiple matching strategies:

            // 1. Exact label match (e.g., "HP 320 FHD Webcam (Device 0)" === "HP 320 FHD Webcam (Device 0)")
            browserMatch = browserDevices.find(bd => bd.label === hc.name);

            // 2. Fuzzy match by checking if browser label contains key parts of backend name
            if (!browserMatch) {
                // Extract key identifying words from backend name (e.g., "HP", "MacBook")
                const backendKeywords = hc.name.toLowerCase().split(/\s+/).filter(w =>
                    w.length > 3 && !['device', 'camera', 'webcam'].includes(w)
                );

                browserMatch = browserDevices.find(bd => {
                    const browserLabel = bd.label.toLowerCase();
                    // Match if browser label contains all key backend keywords
                    return backendKeywords.every(keyword => browserLabel.includes(keyword));
                });
            }

            // 3. Last resort: partial name match (e.g., "HP" in both, "MacBook" in both)
            if (!browserMatch) {
                const backendLower = hc.name.toLowerCase();
                browserMatch = browserDevices.find(bd => {
                    const browserLower = bd.label.toLowerCase();
                    // Check for common brand names
                    if (backendLower.includes('macbook') && browserLower.includes('macbook')) return true;
                    if (backendLower.includes('hp') && browserLower.includes('hp')) return true;
                    if (backendLower.includes('logitech') && browserLower.includes('logitech')) return true;
                    return false;
                });
            }

            console.log(`Camera ${hc.id} (${hc.name}): ${browserMatch ? 'Matched to ' + browserMatch.label : 'No browser match'}`);

            return {
                id: hc.id, // backend ID/index (for saving)
                name: hc.name,
                hardware_id: hc.hardware_id,
                deviceId: browserMatch ? browserMatch.deviceId : null, // for getUserMedia preview
                type: 'stream'
            };
        });

        autoFuzzyMatch();
        renderCameraList();
        renderDisplayList();

    } catch (error) {
        console.error('Fetch cameras failed:', error);
        if (list) list.innerHTML = '<div style="padding:10px; color:var(--status-error);">Discovery service unavailable</div>';
    }
}

/**
 * Automatically reconciles saved display camIds with current hardware session IDs
 * by matching camera names if the original IDs are missing.
 */
function autoFuzzyMatch() {
    console.log('Running auto-fuzzy matching pass...');

    // Helper to normalize camera names by removing device suffix
    function normalizeCameraName(name) {
        return name.replace(/\s*\(Device\s+\d+\)\s*$/i, '').trim().toLowerCase();
    }

    window.appState.displays.forEach(d => {
        if (!d.camera_name) return; // Skip if no saved camera name

        const savedBaseName = normalizeCameraName(d.camera_name);

        // Find matching camera: Priority 1 - Stable hardware_id, Priority 2 - Base name
        const match = window.appState.cameras.find(c => {
            if (d.hardware_id && c.hardware_id === d.hardware_id) return true;
            const currentBaseName = normalizeCameraName(c.name);
            return currentBaseName === savedBaseName;
        });

        if (match) {
            // Update camId if it changed
            if (d.camId !== match.id) {
                console.log(`Auto-remapping display "${d.name}": "${d.camera_name}" -> Camera ID ${match.id} ("${match.name}")`);
                d.camId = match.id;
                // Also update the saved camera_name to match current naming
                d.camera_name = match.name;
            }
        } else {
            // Camera not found - log warning
            console.warn(`Display "${d.name}" configured for camera "${d.camera_name}" but camera not found.`);
        }
    });
}

function renderConfigUI(container) {
    container.innerHTML = `
        <div class="config-layout">
            <aside class="config-sidebar">
                <div class="sidebar-header"><h2>Configuration</h2></div>
                <div class="sidebar-section">
                    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:var(--space-sm);">
                        <h3>Available Cameras</h3>
                        <div style="display:flex; gap:4px;">

                            <button class="btn btn-secondary btn-sm" id="btn-refresh-cameras" style="padding:2px 6px; font-size:0.7rem;">↻</button>
                        </div>
                    </div>
                    <div class="camera-list" id="camera-list"></div>
                </div>
                <div class="sidebar-section" style="flex:1; overflow-y:auto;">
                    <h3>Defined Displays</h3>
                    <div class="display-list" id="display-list"></div>
                </div>
                <div class="sidebar-footer">
                    <button class="btn btn-primary" id="btn-save-config" style="flex:1;">Save & Exit</button>
                    <button class="btn btn-secondary" id="btn-cancel-config">Cancel</button>
                </div>
            </aside>
            <main class="config-main">
                <div class="toolbar-overlay" id="main-toolbar" style="display:none;">
                    <button class="btn btn-secondary btn-sm" id="btn-add-display" title="Add New Display">+ Add Region</button>
                    <div style="width:1px; background:var(--border-subtle); margin:0 4px;"></div>
                    <button class="btn btn-secondary btn-sm" id="btn-undo" title="Undo (Ctrl+Z)" disabled>↶</button>
                    <button class="btn btn-secondary btn-sm" id="btn-redo" title="Redo (Ctrl+Y)" disabled>↷</button>
                    <div style="width:1px; background:var(--border-subtle); margin:0 4px;"></div>
                    <button class="btn btn-secondary btn-sm" id="btn-toggle-view" style="font-size:0.8rem;">View State</button>
                    <div style="width:1px; background:var(--border-subtle); margin:0 4px;"></div>
                    <div class="zoom-control-group" style="display:flex; align-items:center; gap:8px; padding:0 4px;">
                        <span class="text-xs">Zoom</span>
                        <input type="range" id="zoom-slider" min="0.2" max="3" step="0.1" value="1.0" style="width:80px;">
                        <span id="zoom-value" style="font-size:0.7rem; min-width:25px;">100%</span>
                        <button class="btn btn-secondary btn-sm" id="btn-reset-zoom" style="padding:2px 4px; font-size:0.6rem;">Reset</button>
                    </div>
                    <div style="width:1px; background:var(--border-subtle); margin:0 4px;"></div>
                    <span class="text-muted" style="font-size:0.7rem; align-self:center; white-space:nowrap;">💡 Drag edge/corner to resize</span>
                </div>
                <div class="canvas-container fit-view" id="canvas-container">
                    <div id="placeholder-msg" style="color:var(--text-muted);">Select a camera from the sidebar</div>
                    <img id="config-canvas-layer" src="" style="display:none;">
                    <video id="config-video-layer" autoplay playsinline style="display:none;"></video>
                    <div id="overlay-layer" style="position:absolute; top:0; left:0; width:100%; height:100%; pointer-events:none;"></div>
                </div>
                <div class="property-panel" id="property-panel" style="display:none;">
                    <div class="panel-header"><h4>Display Properties</h4><button class="close-btn" id="close-prop-panel">×</button></div>
                    <div class="form-group"><label class="form-label">Display Name</label><input type="text" class="form-input" id="prop-name"></div>
                    <div class="form-group">
                        <label class="form-label">Rotation (°)</label>
                        <input type="number" class="form-input" id="prop-rotation" min="0" max="359">
                    </div>
                    <div class="form-group"><label class="toggle-switch"><input type="checkbox" id="prop-perspective"><span>Enable Perspective Correction</span></label></div>
                    <div style="display:flex; gap:0.5rem; margin-top:1rem;">
                        <button class="btn btn-primary" id="btn-update-display" style="flex:1;">Update</button>
                        <button class="btn btn-danger" id="btn-delete-display">Remove</button>
                    </div>
                </div>
            </main>
        </div>
    `;
    bindCanvasEvents();
    bindEvents();
}

function bindCanvasEvents() {
    const container = document.getElementById('canvas-container');

    container.addEventListener('mousedown', (e) => {
        const rect = container.getBoundingClientRect();
        const mouseX = e.clientX - rect.left;
        const mouseY = e.clientY - rect.top;

        const img = document.getElementById('config-canvas-layer');
        const video = document.getElementById('config-video-layer');
        const target = (video && video.style.display !== 'none') ? video : img;

        if (!target || target.style.display === 'none') {
            console.log('No video/image target found for canvas interaction.');
            return;
        }

        const mediaRect = target.getBoundingClientRect();
        const offsetX = mediaRect.left - rect.left;
        const offsetY = mediaRect.top - rect.top;

        if (mouseX < offsetX || mouseX > offsetX + mediaRect.width || mouseY < offsetY || mouseY > offsetY + mediaRect.height) return;

        const renderedW = mediaRect.width;
        let nativeW = (target.tagName === 'VIDEO') ? target.videoWidth : (target.naturalWidth || target.width);
        const scale = renderedW / (nativeW || 1);

        const visibleDisplays = window.appState.displays.filter(d => d.camId === window.appState.selectedCameraId);
        let clickedOnExisting = false;
        const displayOrder = e.altKey ? visibleDisplays : [...visibleDisplays].reverse();

        for (const d of displayOrder) {
            // Priority 1: Check corner handles
            let handleIdx = -1;
            d.corners.forEach((c, idx) => {
                const sx = offsetX + c.x * scale;
                const sy = offsetY + c.y * scale;
                if (Math.abs(mouseX - sx) < 15 && Math.abs(mouseY - sy) < 15) handleIdx = idx;
            });

            if (handleIdx !== -1) {
                saveState();
                activeDisplayId = d.id;
                activeCornerIndex = handleIdx;
                isResizing = true;
                dragStartX = mouseX;
                dragStartY = mouseY;
                originalCorners = d.corners.map(c => ({ ...c }));
                clickedOnExisting = true;
                renderOverlays();
                break;
            }

            // Priority 2: Check Rotation Handle
            const s0 = { x: offsetX + d.corners[0].x * scale, y: offsetY + d.corners[0].y * scale };
            const s1 = { x: offsetX + d.corners[1].x * scale, y: offsetY + d.corners[1].y * scale };
            const midX = (s0.x + s1.x) / 2;
            const midY = (s0.y + s1.y) / 2;

            // Calculate normal vector for the offset
            const dx = s1.x - s0.x, dy = s1.y - s0.y;
            const len = Math.sqrt(dx * dx + dy * dy) || 1;
            const nx = -dy / len, ny = dx / len;
            const hrx = midX + nx * 40, hry = midY + ny * 40;

            if (Math.abs(mouseX - hrx) < 15 && Math.abs(mouseY - hry) < 15) {
                saveState();
                activeDisplayId = d.id;
                isRotating = true;
                displayCenter = getPolyCenter(d.corners);
                rotateStartAngle = Math.atan2(mouseY - (offsetY + displayCenter.y * scale), mouseX - (offsetX + displayCenter.x * scale)) * 180 / Math.PI;
                rotateStartValue = d.rotation || 0;
                originalCorners = d.corners.map(c => ({ ...c }));
                clickedOnExisting = true;
                renderOverlays();
                break;
            }

            // Priority 3: Check Sides (Resizing)
            let sideIdx = -1;
            for (let i = 0; i < 4; i++) {
                const head = d.corners[i];
                const tail = d.corners[(i + 1) % 4];
                const sH = { x: offsetX + head.x * scale, y: offsetY + head.y * scale };
                const sT = { x: offsetX + tail.x * scale, y: offsetY + tail.y * scale };
                if (distToSegment({ x: mouseX, y: mouseY }, sH, sT) < 10) {
                    sideIdx = i;
                    break;
                }
            }

            if (sideIdx !== -1) {
                saveState();
                activeDisplayId = d.id;
                activeSideIndex = sideIdx;
                isResizing = false; // We are side-resizing
                dragStartX = mouseX;
                dragStartY = mouseY;
                originalCorners = d.corners.map(c => ({ ...c }));
                clickedOnExisting = true;
                renderOverlays();
                break;
            }

            // Priority 4: Check polygon interior (Dragging)
            const nativePt = { x: (mouseX - offsetX) / scale, y: (mouseY - offsetY) / scale };
            if (isPointInPoly(nativePt, d.corners)) {
                saveState();
                activeDisplayId = d.id;
                isDragging = true;
                dragStartX = mouseX;
                dragStartY = mouseY;
                originalCorners = d.corners.map(c => ({ ...c }));
                clickedOnExisting = true;
                openPropertyPanel(d);
                renderOverlays();
                break;
            }
        }

        if (!clickedOnExisting && target && target.style.display !== 'none') {
            saveState();
            isDrawing = true;
            const nx = (mouseX - offsetX) / scale;
            const ny = (mouseY - offsetY) / scale;
            const id = 'disp_' + Date.now();
            const newD = {
                id, name: 'New Display', camId: window.appState.selectedCameraId,
                corners: [{ x: nx, y: ny }, { x: nx, y: ny }, { x: nx, y: ny }, { x: nx, y: ny }],
                rotation: 0, enablePerspective: false
            };
            window.appState.displays.push(newD);
            activeDisplayId = id;
            drawingDisplayId = id;
            activeCornerIndex = 2; // Move bottom-right as we drag
            originalCorners = newD.corners.map(c => ({ ...c }));
            dragStartX = mouseX;
            dragStartY = mouseY;
        }
        e.preventDefault();
    });

    window.addEventListener('mousemove', (e) => {
        if (!isDragging && !isResizing && !isDrawing && !isRotating && activeSideIndex === -1) return;
        const rect = container.getBoundingClientRect();
        const mouseX = e.clientX - rect.left;
        const mouseY = e.clientY - rect.top;
        const dx = mouseX - dragStartX;
        const dy = mouseY - dragStartY;

        const d = window.appState.displays.find(x => x.id === activeDisplayId);
        if (!d) return;

        const img = document.getElementById('config-canvas-layer');
        const video = document.getElementById('config-video-layer');
        const target = (video && video.style.display !== 'none') ? video : img;
        const mediaRect = target.getBoundingClientRect();
        const ox = mediaRect.left - rect.left;
        const oy = mediaRect.top - rect.top;
        const scale = mediaRect.width / (target.videoWidth || target.naturalWidth || target.width || 1);

        const ndx = dx / scale;
        const ndy = dy / scale;

        if (isRotating) {
            const currentAngle = Math.atan2(mouseY - (oy + displayCenter.y * scale), mouseX - (ox + displayCenter.x * scale)) * 180 / Math.PI;
            let delta = currentAngle - rotateStartAngle;

            // Physically rotate the corners
            d.corners = rotatePoints(originalCorners, displayCenter, delta);

            // Keep rotation property in sync for persistence/orientation logic (cumulative)
            d.rotation = (rotateStartValue + Math.round(delta)) % 360;
            if (d.rotation < 0) d.rotation += 360;

            const rotEl = document.getElementById('prop-rotation');
            if (rotEl) rotEl.value = d.rotation;
        } else if (isDrawing) {
            d.corners[1].x = originalCorners[1].x + ndx;
            d.corners[2].x = originalCorners[2].x + ndx;
            d.corners[2].y = originalCorners[2].y + ndy;
            d.corners[3].y = originalCorners[3].y + ndy;
        } else if (isDragging) {
            d.corners = originalCorners.map(c => ({ x: c.x + ndx, y: c.y + ndy }));
        } else if (isResizing) {
            d.corners[activeCornerIndex].x = originalCorners[activeCornerIndex].x + ndx;
            d.corners[activeCornerIndex].y = originalCorners[activeCornerIndex].y + ndy;
        } else if (activeSideIndex !== -1) {
            // Move BOTH points of the side
            const i1 = activeSideIndex;
            const i2 = (activeSideIndex + 1) % 4;
            d.corners[i1].x = originalCorners[i1].x + ndx;
            d.corners[i1].y = originalCorners[i1].y + ndy;
            d.corners[i2].x = originalCorners[i2].x + ndx;
            d.corners[i2].y = originalCorners[i2].y + ndy;
        }
        renderOverlays();
    });

    window.addEventListener('mouseup', () => {
        if (isDrawing && drawingDisplayId) {
            const d = window.appState.displays.find(x => x.id === drawingDisplayId);
            if (d) {
                const w = Math.abs(d.corners[0].x - d.corners[2].x);
                const h = Math.abs(d.corners[0].y - d.corners[2].y);
                if (w < 20 || h < 20) {
                    window.appState.displays = window.appState.displays.filter(x => x.id !== drawingDisplayId);
                    activeDisplayId = null;
                } else {
                    openPropertyPanel(d);
                }
            }
        }
        isDragging = isResizing = isDrawing = isRotating = false;
        activeCornerIndex = -1;
        activeSideIndex = -1;
        renderOverlays();
        renderDisplayList();
    });
}

function isPointInPoly(pt, poly) {
    let c = false;
    for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
        if (((poly[i].y <= pt.y && pt.y < poly[j].y) || (poly[j].y <= pt.y && pt.y < poly[i].y)) &&
            (pt.x < (poly[j].x - poly[i].x) * (pt.y - poly[i].y) / (poly[j].y - poly[i].y) + poly[i].x)) c = !c;
    }
    return c;
}

/**
 * Calculates distance from point p to line segment v-w
 */
function distToSegment(p, v, w) {
    const l2 = (v.x - w.x) ** 2 + (v.y - w.y) ** 2;
    if (l2 === 0) return Math.sqrt((p.x - v.x) ** 2 + (p.y - v.y) ** 2);
    let t = ((p.x - v.x) * (w.x - v.x) + (p.y - v.y) * (w.y - v.y)) / l2;
    t = Math.max(0, Math.min(1, t));
    return Math.sqrt((p.x - (v.x + t * (w.x - v.x))) ** 2 + (p.y - (v.y + t * (w.y - v.y))) ** 2);
}

function getPolyCenter(poly) {
    const x = poly.reduce((sum, p) => sum + p.x, 0) / poly.length;
    const y = poly.reduce((sum, p) => sum + p.y, 0) / poly.length;
    return { x, y };
}

/**
 * Rotates a point around a center.
 */
function rotatePoint(p, center, angleDeg) {
    const rad = angleDeg * Math.PI / 180;
    const s = Math.sin(rad);
    const c = Math.cos(rad);
    const px = p.x - center.x;
    const py = p.y - center.y;
    return {
        x: px * c - py * s + center.x,
        y: px * s + py * c + center.y
    };
}

function rotatePoints(points, center, angleDeg) {
    return points.map(p => rotatePoint(p, center, angleDeg));
}

function renderOverlays() {
    const layer = document.getElementById('overlay-layer');
    if (!layer) return;

    // Clear everything first to prevent old handles/labels from sticking
    layer.innerHTML = '';

    const img = document.getElementById('config-canvas-layer');
    const video = document.getElementById('config-video-layer');
    const target = (video && video.style.display !== 'none') ? video : img;

    // If no target is visible, just return after clearing
    if (!target || target.style.display === 'none') return;
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("class", "poly-overlay");
    layer.appendChild(svg);

    const rect = document.getElementById('canvas-container').getBoundingClientRect();
    const mediaRect = target.getBoundingClientRect();
    const ox = mediaRect.left - rect.left;
    const oy = mediaRect.top - rect.top;
    const scale = mediaRect.width / (target.videoWidth || target.naturalWidth || target.width || 1);

    window.appState.displays.filter(d => d.camId === window.appState.selectedCameraId).forEach(d => {
        // Safe corners for rendering
        const corners = d.corners || [
            { x: d.x, y: d.y },
            { x: d.x + d.w, y: d.y },
            { x: d.x + d.w, y: d.y + d.h },
            { x: d.x, y: d.y + d.h }
        ];

        const points = corners.map(c => `${ox + c.x * scale},${oy + c.y * scale}`).join(' ');
        const poly = document.createElementNS("http://www.w3.org/2000/svg", "polygon");
        poly.setAttribute("points", points);
        poly.setAttribute("class", `poly-shape ${d.id === activeDisplayId ? 'active' : 'inactive'}`);
        svg.appendChild(poly);

        if (d.id === activeDisplayId) {
            corners.forEach(c => {
                const handle = document.createElement('div');
                handle.className = 'resize-handle';
                handle.style.left = (ox + c.x * scale - 7) + 'px';
                handle.style.top = (oy + c.y * scale - 7) + 'px';
                layer.appendChild(handle);
            });

            // Draw Rotation Handle
            const s0 = { x: ox + corners[0].x * scale, y: oy + corners[0].y * scale };
            const s1 = { x: ox + corners[1].x * scale, y: oy + corners[1].y * scale };
            const midX = (s0.x + s1.x) / 2;
            const midY = (s0.y + s1.y) / 2;

            const dx = s1.x - s0.x, dy = s1.y - s0.y;
            const len = Math.sqrt(dx * dx + dy * dy) || 1;
            const nx = -dy / len, ny = dx / len;
            const hrx = midX + nx * 40, hry = midY + ny * 40;

            const rotLine = document.createElementNS("http://www.w3.org/2000/svg", "line");
            rotLine.setAttribute("x1", midX);
            rotLine.setAttribute("y1", midY);
            rotLine.setAttribute("x2", hrx);
            rotLine.setAttribute("y2", hry);
            rotLine.setAttribute("stroke", "var(--status-warning)");
            rotLine.setAttribute("stroke-width", "2");
            svg.appendChild(rotLine);

            const rotHandle = document.createElement('div');
            rotHandle.className = 'perspective-point'; // Use existing style
            rotHandle.style.background = 'var(--status-warning)';
            rotHandle.style.left = (hrx - 7) + 'px';
            rotHandle.style.top = (hry - 7) + 'px';
            layer.appendChild(rotHandle);

            const label = document.createElement('div');
            label.innerText = d.name;
            label.className = 'display-label'; // Use a class for consistency
            label.style.position = 'absolute';
            label.style.left = (ox + corners[0].x * scale) + 'px';
            label.style.top = (oy + corners[0].y * scale - 25) + 'px';
            label.style.background = 'var(--accent)';
            label.style.color = 'white';
            label.style.padding = '2px 6px';
            label.style.borderRadius = '4px';
            label.style.fontSize = '12px';
            layer.appendChild(label);
        }
    });
}

function bindEvents() {
    document.getElementById('btn-cancel-config').addEventListener('click', () => { stopActiveStream(); navigateTo('landing-view'); });
    document.getElementById('btn-save-config').addEventListener('click', async () => { if (await saveConfig()) { stopActiveStream(); navigateTo('landing-view'); } });
    document.getElementById('btn-add-display').addEventListener('click', startAddDisplayMode);
    document.getElementById('close-prop-panel').addEventListener('click', () => { activeDisplayId = null; renderOverlays(); document.getElementById('property-panel').style.display = 'none'; });
    document.getElementById('btn-update-display').addEventListener('click', () => {
        const d = window.appState.displays.find(x => x.id === activeDisplayId);
        if (d) {
            saveState();
            d.name = document.getElementById('prop-name').value;
            d.rotation = parseInt(document.getElementById('prop-rotation').value);
            d.enablePerspective = document.getElementById('prop-perspective').checked;
            renderOverlays(); renderDisplayList();

            // Provide feedback
            const btn = document.getElementById('btn-update-display');
            const originalText = btn.innerText;
            btn.innerText = 'Applied!';
            btn.classList.replace('btn-primary', 'btn-success');
            setTimeout(() => {
                btn.innerText = originalText;
                btn.classList.replace('btn-success', 'btn-primary');
            }, 2000);
        }
    });
    document.getElementById('btn-delete-display').addEventListener('click', () => {
        saveState();
        window.appState.displays = window.appState.displays.filter(x => x.id !== activeDisplayId);
        activeDisplayId = null; renderOverlays(); renderDisplayList(); document.getElementById('property-panel').style.display = 'none';
        updateUndoRedoButtons();
    });
    document.getElementById('btn-refresh-cameras').addEventListener('click', async () => {
        try {
            await fetch('/api/cameras/reset', { method: 'POST' });
            console.log('Cameras reset on backend.');
        } catch (e) {
            console.error('Reset failed:', e);
        }
        fetchCameras();
    });

    document.getElementById('btn-toggle-view').addEventListener('click', () => {
        viewMode = (viewMode === 'fit') ? 'native' : 'fit';
        const container = document.getElementById('canvas-container');

        if (viewMode === 'native') {
            container.classList.replace('fit-view', 'native-view');
            document.getElementById('btn-toggle-view').innerText = 'View: Native';
        } else {
            container.classList.replace('native-view', 'fit-view');
            document.getElementById('btn-toggle-view').innerText = 'View: Fit';
        }
        applyZoom(1.0);
    });

    document.getElementById('btn-undo').addEventListener('click', undo);
    document.getElementById('btn-redo').addEventListener('click', redo);

    const zoomSlider = document.getElementById('zoom-slider');
    const zoomValue = document.getElementById('zoom-value');
    const btnResetZoom = document.getElementById('btn-reset-zoom');

    zoomSlider.addEventListener('input', (e) => applyZoom(e.target.value));
    btnResetZoom.addEventListener('click', () => applyZoom(1.0));

    window.addEventListener('keydown', (e) => {
        if (e.target.tagName === 'INPUT') return; // Don't trigger while typing

        if ((e.ctrlKey || e.metaKey) && e.key === 'z') {
            e.preventDefault();
            if (e.shiftKey) redo();
            else undo();
        } else if ((e.ctrlKey || e.metaKey) && e.key === 'y') {
            e.preventDefault();
            redo();
        }
    });
}

window.selectCamera = function (id) {
    if (!id) return;

    // Check if we need fuzzy matching (saved ID hash might have changed)
    let cam = window.appState.cameras.find(c => c.id === id);

    if (!cam) {
        // Try fuzzy match by name if this ID came from a saved display
        const savedDisplayWithId = window.appState.displays.find(d => d.camId === id);
        if (savedDisplayWithId && savedDisplayWithId.camera_name) {
            cam = window.appState.cameras.find(c => c.name.trim() === savedDisplayWithId.camera_name.trim());
            if (cam) {
                console.log(`Fuzzy matched camera "${cam.name}" by name. Updating display camId.`);
                // Update all displays using this old ID to the new session ID
                window.appState.displays.forEach(d => {
                    if (d.camId === id) d.camId = cam.id;
                });
                id = cam.id;
            }
        }
    }

    window.appState.selectedCameraId = id;

    if (!cam) {
        console.warn('Camera not located in current session:', id);
        // Refresh UI even if cam is missing to show "selection border"
        renderOverlays();
        renderDisplayList();

        const msg = document.getElementById('placeholder-msg');
        if (msg) {
            msg.innerText = 'Camera connection lost for this display. Please select an available camera from the left.';
            msg.style.display = 'block';
        }
        return;
    }

    // Highlight selected camera in sidebar
    document.querySelectorAll('.camera-list .list-item').forEach(el => {
        el.classList.toggle('selected', el.innerText.trim() === cam.name);
    });

    const img = document.getElementById('config-canvas-layer');
    const video = document.getElementById('config-video-layer');
    const msg = document.getElementById('placeholder-msg');
    const toolbar = document.getElementById('main-toolbar');

    img.style.display = 'none';
    video.style.display = 'none';
    stopActiveStream();

    if (cam.type === 'stream') {
        if (!cam.deviceId) {
            msg.innerText = 'Camera detected by backend but browser cannot access it. Check browser permissions or try refreshing the page.';
            msg.style.display = 'block';
            toolbar.style.display = 'none';
            renderOverlays();
            renderDisplayList();
            return;
        }

        const constraintId = cam.deviceId;
        navigator.mediaDevices.getUserMedia({ video: { deviceId: { exact: constraintId } } })
            .then(stream => {
                video.srcObject = stream;
                video.style.display = 'block';
                msg.style.display = 'none';
                toolbar.style.display = 'flex';
                video.onloadedmetadata = () => {
                    applyZoom(1.0);
                    renderDisplayList();
                };
            })
            .catch(err => {
                console.error('Failed to access camera:', err);
                msg.innerText = 'Error accessing camera. Please check permissions and device availability.';
                msg.style.display = 'block';
                renderOverlays();
                renderDisplayList();
            });
    } else {
        img.src = cam.src;
        img.onload = () => {
            img.style.display = 'block';
            msg.style.display = 'none';
            toolbar.style.display = 'flex';
            applyZoom(1.0);
            renderDisplayList();
        };
    }
};

function startAddDisplayMode() {
    saveState();
    if (!window.appState.selectedCameraId) {
        alert('Please select a camera first before adding a display region.');
        return;
    }
    const id = 'disp_' + Date.now();
    const newD = {
        id,
        name: 'New Display',
        camId: window.appState.selectedCameraId,
        x: 100, y: 100, w: 300, h: 180,
        rotation: 0,
        enablePerspective: false,
        corners: [{ x: 100, y: 100 }, { x: 400, y: 100 }, { x: 400, y: 280 }, { x: 100, y: 280 }]
    };
    window.appState.displays.push(newD);
    activeDisplayId = id;
    renderOverlays();
    renderDisplayList();
    openPropertyPanel(newD);
}

function renderDisplayList() {
    const list = document.getElementById('display-list');
    if (!list) return;
    if (window.appState.displays.length === 0) {
        list.innerHTML = '<p class="text-muted" style="padding:10px;">No displays added yet.</p>';
        return;
    }
    list.innerHTML = window.appState.displays.map(d => {
        // Find if the configured camera (by name) is currently available
        const configuredCameraName = d.camera_name || 'Unknown Camera';
        const isCameraConnected = window.appState.cameras.some(c => {
            // Fuzzy match: check if camera names are similar
            const cLower = c.name.toLowerCase();
            const dLower = configuredCameraName.toLowerCase();
            return cLower === dLower ||
                cLower.includes(dLower.split('(')[0].trim().toLowerCase()) ||
                dLower.includes(cLower.split('(')[0].trim().toLowerCase());
        });

        const isSelected = d.id === activeDisplayId;

        return `
            <div class="list-item ${isSelected ? 'selected' : ''}" onclick="selectDisplayFromList('${d.id}')">
                <div style="width:10px; height:10px; background:${isCameraConnected ? 'var(--status-active)' : 'var(--status-off)'}; border-radius:50%;"></div>
                <div style="flex:1;">
                    <div style="font-weight:500;">${d.name}</div>
                    <div style="font-size:0.75rem; color:var(--text-muted);">${configuredCameraName}</div>
                </div>
            </div>
        `;
    }).join('');
}

window.selectDisplayFromList = function (id) {
    console.log('Selecting display by ID:', id);
    const d = window.appState.displays.find(x => x.id === id);
    if (!d) {
        console.warn('Display not found:', id);
        return;
    }

    activeDisplayId = id;

    // Switch camera if it exists and is different
    if (d.camId !== window.appState.selectedCameraId) {
        window.selectCamera(d.camId);
    } else {
        renderOverlays();
        renderDisplayList(); // Ensure sidebar selection reflects
    }

    openPropertyPanel(d);
};

function openPropertyPanel(d) {
    const panel = document.getElementById('property-panel');
    if (!panel) return;
    panel.style.display = 'block';
    document.getElementById('prop-name').value = d.name;
    document.getElementById('prop-rotation').value = d.rotation;
    document.getElementById('prop-perspective').checked = d.enablePerspective;
}

function renderCameraList() {
    document.getElementById('camera-list').innerHTML = window.appState.cameras.map(c => `<div class="list-item" onclick="selectCamera('${c.id}')"><div style="font-weight:500;">${c.name}</div></div>`).join('');
}

function applyZoom(val) {
    visualScale = parseFloat(val);
    const zoomSlider = document.getElementById('zoom-slider');
    const zoomValue = document.getElementById('zoom-value');
    if (zoomSlider) zoomSlider.value = val;
    if (zoomValue) zoomValue.innerText = `${Math.round(val * 100)}%`;

    const video = document.getElementById('config-video-layer');
    const img = document.getElementById('config-canvas-layer');
    [video, img].forEach(el => {
        if (el) {
            if (viewMode === 'native') {
                const nativeW = (el.tagName === 'VIDEO') ? el.videoWidth : (el.naturalWidth || el.width);
                el.style.width = (nativeW * visualScale) + 'px';
                el.style.maxWidth = 'none';
                el.style.maxHeight = 'none';
            } else {
                el.style.width = (visualScale * 95) + '%';
                el.style.maxWidth = 'none';
                el.style.maxHeight = 'none';
            }
        }
    });
    renderOverlays();
}
