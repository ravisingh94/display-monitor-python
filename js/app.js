import { initConfigMode } from './config.js';
import { initMonitorMode } from './monitor.js';
import { initVideoAnalysisMode } from './video_analysis.js';

// Global App State
window.appState = {
    cameras: [
        { id: 'cam1', name: 'Interior Camera 01 (Fish-eye)', src: 'assets/camera_feed_01.png' },
        { id: 'cam2', name: 'Cluster Camera', src: 'assets/camera_feed_01.png' } // Reusing same img for demo
    ],
    selectedCameraId: null,
    displays: []
};

document.addEventListener('DOMContentLoaded', () => {
    // Navigation Logic
    const btnStartConfig = document.getElementById('btn-start-config');
    const btnStartMonitor = document.getElementById('btn-start-monitor');
    const btnStartVideo = document.getElementById('btn-start-video-analysis');

    btnStartConfig.addEventListener('click', () => {
        navigateTo('config-view');
    });

    btnStartMonitor.addEventListener('click', () => {
        navigateTo('monitor-view');
    });

    if (btnStartVideo) {
        btnStartVideo.addEventListener('click', () => {
            navigateTo('video-analysis-view');
        });
    }
});

export function navigateTo(viewId) {
    // Hide all views
    document.querySelectorAll('.view-container').forEach(el => {
        el.classList.remove('active');
        // Clear content if needed to save memory/state
        if (el.id !== 'landing-view') el.innerHTML = '';
    });

    // Show landing if requested (back)
    if (viewId === 'landing-view') {
        document.getElementById('landing-view').classList.add('active');
        setCameraState(false);
        return;
    }

    // Create and inject view dynamically
    const app = document.getElementById('app');
    let view = document.getElementById(viewId);

    if (!view) {
        view = document.createElement('div');
        view.id = viewId;
        view.className = 'view-container active';
        app.appendChild(view);
    } else {
        view.classList.add('active');
    }

    // Initialize View Controller
    if (viewId === 'config-view') {
        initConfigMode(view);
    } else if (viewId === 'monitor-view') {
        setCameraState(true);
        initMonitorMode(view);
    } else if (viewId === 'video-analysis-view') {
        setCameraState(false);
        initVideoAnalysisMode(view);
    } else {
        setCameraState(false);
    }
}

async function setCameraState(active) {
    const endpoint = active ? '/api/monitor/start' : '/api/monitor/stop';
    try {
        const res = await fetch(endpoint, { method: 'POST' });
        const data = await res.json();
        console.log(`[CameraState] Request: ${active}, Response:`, data);
    } catch (e) {
        console.error(`[CameraState] Failed to set state ${active}:`, e);
    }
}
