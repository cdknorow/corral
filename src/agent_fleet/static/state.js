/* Shared application state */

export const state = {
    currentSession: null,       // { type: "live"|"history", name: string, agent_type?: string }
    fleetWs: null,              // WebSocket for fleet updates
    captureInterval: null,      // interval ID for auto-refreshing capture
    autoScroll: true,
    liveSessions: [],           // cached live session list
    historySessionsList: [],    // cached history session list (from last paginated fetch)
    currentCommands: {},        // commands for current session's agent type
    sessionInputText: {},       // per-session draft text: { "sessionKey": "partial text" }
};

export function sessionKey(session) {
    if (!session) return null;
    return `${session.type}:${session.name}`;
}

export const CAPTURE_REFRESH_MS = 2000;
