/* WebSocket connection for real-time fleet updates */

import { state } from './state.js';
import { renderLiveSessions, updateSessionStatus, updateSessionSummary, updateSessionBranch } from './render.js';

export function connectFleetWs() {
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    const url = `${proto}//${location.host}/ws/fleet`;

    state.fleetWs = new WebSocket(url);

    state.fleetWs.onmessage = (event) => {
        const data = JSON.parse(event.data);
        if (data.type === "fleet_update") {
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

    state.fleetWs.onclose = () => {
        setTimeout(connectFleetWs, 5000);
    };

    state.fleetWs.onerror = () => {
        // Will trigger onclose
    };
}
