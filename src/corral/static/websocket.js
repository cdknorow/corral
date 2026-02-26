/* WebSocket connection for real-time corral updates */

import { state } from './state.js';
import { renderLiveSessions, updateSessionStatus, updateSessionSummary, updateSessionBranch } from './render.js';

export function connectCorralWs() {
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    const url = `${proto}//${location.host}/ws/corral`;

    state.corralWs = new WebSocket(url);

    state.corralWs.onmessage = (event) => {
        const data = JSON.parse(event.data);
        if (data.type === "corral_update") {
            state.liveSessions = data.sessions;
            renderLiveSessions(data.sessions);

            // Update status/summary/branch if we're viewing a live session
            if (state.currentSession && state.currentSession.type === "live") {
                const s = data.sessions.find(s => s.name === state.currentSession.name);
                if (s) {
                    updateSessionStatus(s.status);
                    updateSessionSummary(s.summary);
                    updateSessionBranch(s.branch);
                }
            }
        }
    };

    state.corralWs.onclose = () => {
        setTimeout(connectCorralWs, 5000);
    };

    state.corralWs.onerror = () => {
        // Will trigger onclose
    };
}
