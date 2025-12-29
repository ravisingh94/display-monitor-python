/**
 * Single Tab Enforcer
 * Ensures only one browser tab/window can access the application at a time
 * Uses the Broadcast Channel API for cross-tab communication
 */

class SingleTabEnforcer {
    constructor() {
        this.tabId = `tab-${Date.now()}-${Math.random()}`;
        this.channel = new BroadcastChannel('display_monitor_single_tab');
        this.isActive = false;
        this.checkTimeout = null;

        console.log(`[SingleTabEnforcer] Initializing tab ${this.tabId}`);
        this.init();
    }

    init() {
        // Listen for messages from other tabs
        this.channel.onmessage = (event) => {
            const { type, tabId } = event.data;

            // Ignore messages from this tab
            if (tabId === this.tabId) return;

            console.log(`[SingleTabEnforcer] Received ${type} from tab ${tabId}`);

            switch (type) {
                case 'NEW_TAB':
                    // New tab opened - if we're already active, tell them to close
                    if (this.isActive) {
                        console.log(`[SingleTabEnforcer] We're active, telling new tab to close`);
                        this.channel.postMessage({ type: 'ACTIVE_TAB_EXISTS', tabId: this.tabId });
                    }
                    break;

                case 'ACTIVE_TAB_EXISTS':
                    // Another tab is already active - we should close
                    console.log(`[SingleTabEnforcer] Another tab is active, closing this tab`);
                    this.showWarningAndClose('Another tab is already open. Only one tab is allowed.');
                    break;

                case 'PING':
                    // Respond to ping if we're active
                    if (this.isActive) {
                        this.channel.postMessage({ type: 'PONG', tabId: this.tabId });
                    }
                    break;

                case 'PONG':
                    // Another active tab responded to our ping - we should close
                    console.log(`[SingleTabEnforcer] Active tab responded, closing this tab`);
                    this.showWarningAndClose('Another tab is already active. Only one tab is allowed.');
                    break;

                case 'TAB_CLOSED':
                    console.log(`[SingleTabEnforcer] Another tab closed`);
                    break;
            }
        };

        // Announce this tab's presence and check for existing tabs
        this.channel.postMessage({ type: 'NEW_TAB', tabId: this.tabId });
        this.channel.postMessage({ type: 'PING', tabId: this.tabId });

        // Wait for responses - if no PONG received, this tab becomes active
        this.checkTimeout = setTimeout(() => {
            if (!this.isActive) {
                console.log(`[SingleTabEnforcer] No active tabs detected, this tab is now active`);
                this.isActive = true;
            }
        }, 200);

        // Clean up when tab closes
        window.addEventListener('beforeunload', () => {
            console.log(`[SingleTabEnforcer] Tab closing, broadcasting closure`);
            this.channel.postMessage({ type: 'TAB_CLOSED', tabId: this.tabId });
            this.cleanup();
        });

        // Handle visibility changes (tab switching)
        document.addEventListener('visibilitychange', () => {
            if (document.hidden) {
                console.log(`[SingleTabEnforcer] Tab hidden`);
            } else {
                console.log(`[SingleTabEnforcer] Tab visible again`);
            }
        });
    }

    showWarningAndClose(message) {
        // Clear any pending check timeout
        if (this.checkTimeout) {
            clearTimeout(this.checkTimeout);
        }

        // Create modal overlay
        const overlay = document.createElement('div');
        overlay.id = 'single-tab-overlay';
        overlay.style.cssText = `
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0, 0, 0, 0.95);
            display: flex;
            align-items: center;
            justify-content: center;
            z-index: 999999;
            color: white;
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            animation: fadeIn 0.3s ease-in;
        `;

        const messageBox = document.createElement('div');
        messageBox.style.cssText = `
            background: linear-gradient(135deg, #dc3545 0%, #c82333 100%);
            padding: 40px 60px;
            border-radius: 12px;
            text-align: center;
            max-width: 500px;
            box-shadow: 0 20px 60px rgba(0, 0, 0, 0.5);
            animation: slideIn 0.3s ease-out;
        `;

        messageBox.innerHTML = `
            <div style="font-size: 48px; margin-bottom: 20px;">⚠️</div>
            <h2 style="margin: 0 0 20px 0; font-size: 24px; font-weight: 700;">Multiple Tabs Detected</h2>
            <p style="font-size: 16px; margin: 0 0 24px 0; line-height: 1.6; opacity: 0.95;">${message}</p>
            <div style="display: inline-block; padding: 8px 20px; background: rgba(255, 255, 255, 0.2); border-radius: 20px; font-size: 14px;">
                <span id="countdown">3</span>s until close...
            </div>
        `;

        overlay.appendChild(messageBox);
        document.body.appendChild(overlay);

        // Add animations
        const style = document.createElement('style');
        style.textContent = `
            @keyframes fadeIn {
                from { opacity: 0; }
                to { opacity: 1; }
            }
            @keyframes slideIn {
                from { transform: translateY(-30px); opacity: 0; }
                to { transform: translateY(0); opacity: 1; }
            }
        `;
        document.head.appendChild(style);

        // Countdown timer
        let countdown = 3;
        const countdownElement = document.getElementById('countdown');
        const countdownInterval = setInterval(() => {
            countdown--;
            if (countdownElement) {
                countdownElement.textContent = countdown;
            }
            if (countdown <= 0) {
                clearInterval(countdownInterval);
            }
        }, 1000);

        // Close the tab after 3 seconds
        setTimeout(() => {
            window.close();

            // If window.close() fails (some browsers block it for tabs not opened by script)
            // Try alternative approaches
            setTimeout(() => {
                // Try to navigate away
                window.location.href = 'about:blank';

                // Or show a message asking user to close manually
                setTimeout(() => {
                    if (messageBox) {
                        messageBox.innerHTML = `
                            <div style="font-size: 48px; margin-bottom: 20px;">⚠️</div>
                            <h2 style="margin: 0 0 20px 0; font-size: 24px; font-weight: 700;">Please Close This Tab</h2>
                            <p style="font-size: 16px; margin: 0; line-height: 1.6; opacity: 0.95;">
                                Your browser prevented automatic closure.<br>
                                Please close this tab manually.
                            </p>
                        `;
                    }
                }, 1000);
            }, 500);
        }, 3000);
    }

    cleanup() {
        if (this.checkTimeout) {
            clearTimeout(this.checkTimeout);
        }
        this.channel.close();
    }
}

// Initialize when DOM is ready, but only if enabled in config
async function initializeSingleTabEnforcer() {
    try {
        // Check if single-tab enforcement is enabled in config
        const response = await fetch('/api/app/config');
        const config = await response.json();

        if (config.single_tab_enforcement === false) {
            console.log('[SingleTabEnforcer] Single-tab enforcement is DISABLED in config.yaml');
            return; // Don't enforce
        }

        console.log('[SingleTabEnforcer] Single-tab enforcement is ENABLED');
        window.singleTabEnforcer = new SingleTabEnforcer();
    } catch (error) {
        console.error('[SingleTabEnforcer] Error loading config, defaulting to ENABLED:', error);
        // Default to enabled if config can't be loaded
        window.singleTabEnforcer = new SingleTabEnforcer();
    }
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initializeSingleTabEnforcer);
} else {
    // DOM already loaded
    initializeSingleTabEnforcer();
}

// Export for module usage
export default SingleTabEnforcer;
