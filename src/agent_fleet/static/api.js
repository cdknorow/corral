/* REST API fetch functions */

import { state } from './state.js';
import { renderLiveSessions, renderHistorySessions } from './render.js';

export async function loadLiveSessions() {
    try {
        const resp = await fetch("/api/sessions/live");
        state.liveSessions = await resp.json();
        renderLiveSessions(state.liveSessions);
    } catch (e) {
        console.error("Failed to load live sessions:", e);
    }
}

export async function loadHistorySessions() {
    try {
        const resp = await fetch("/api/sessions/history");
        const sessions = await resp.json();
        renderHistorySessions(sessions);
    } catch (e) {
        console.error("Failed to load history sessions:", e);
    }
}

export async function loadLiveSessionDetail(name, agentType) {
    try {
        let url = `/api/sessions/live/${encodeURIComponent(name)}`;
        if (agentType) url += `?agent_type=${encodeURIComponent(agentType)}`;
        const resp = await fetch(url);
        return await resp.json();
    } catch (e) {
        console.error("Failed to load session detail:", e);
        return null;
    }
}

export async function loadHistoryMessages(sessionId) {
    try {
        const resp = await fetch(`/api/sessions/history/${encodeURIComponent(sessionId)}`);
        return await resp.json();
    } catch (e) {
        console.error("Failed to load history messages:", e);
        return null;
    }
}
