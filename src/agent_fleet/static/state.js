/* Shared application state */

export const state = {
    currentSession: null,       // { type: "live"|"history", name: string, agent_type?: string }
    fleetWs: null,              // WebSocket for fleet updates
    captureInterval: null,      // interval ID for auto-refreshing capture
    autoScroll: true,
    liveSessions: [],           // cached live session list
    currentCommands: {},        // commands for current session's agent type
};

export const CAPTURE_REFRESH_MS = 2000;
