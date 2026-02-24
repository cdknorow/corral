/* Session selection and management */

import { state } from './state.js';
import { showToast } from './utils.js';
import { loadLiveSessionDetail, loadHistoryMessages } from './api.js';
import { stopCaptureRefresh, startCaptureRefresh } from './capture.js';
import { updateSessionStatus, updateSessionSummary, renderHistoryChat } from './render.js';
import { renderQuickActions, updateSidebarActive } from './controls.js';

export async function selectLiveSession(name, agentType) {
    stopCaptureRefresh();

    state.currentSession = { type: "live", name, agent_type: agentType || null };

    // Show live view, hide others
    document.getElementById("welcome-screen").style.display = "none";
    document.getElementById("history-session-view").style.display = "none";
    document.getElementById("live-session-view").style.display = "flex";

    // Update header
    document.getElementById("session-name").textContent = name;
    const badge = document.getElementById("session-type-badge");
    badge.textContent = agentType || "claude";
    badge.className = `badge ${(agentType || "claude").toLowerCase()}`;

    // Load detail for status/summary
    const detail = await loadLiveSessionDetail(name, agentType);
    if (detail) {
        updateSessionStatus(detail.status);
        updateSessionSummary(detail.summary);

        // Show initial pane capture
        if (detail.pane_capture) {
            document.getElementById("pane-capture").textContent = detail.pane_capture;
        }
    }

    // Set up quick action buttons
    const agent = state.liveSessions.find(s => s.name === name);
    state.currentCommands = (agent && agent.commands) || { compress: "/compact", clear: "/clear" };
    renderQuickActions();

    // Highlight in sidebar
    updateSidebarActive();

    // Start auto-refreshing capture
    startCaptureRefresh();
}

export async function selectHistorySession(sessionId) {
    stopCaptureRefresh();

    state.currentSession = { type: "history", name: sessionId };

    document.getElementById("welcome-screen").style.display = "none";
    document.getElementById("live-session-view").style.display = "none";
    document.getElementById("history-session-view").style.display = "flex";

    document.getElementById("history-session-title").textContent = `Session: ${sessionId}`;

    updateSidebarActive();

    const data = await loadHistoryMessages(sessionId);
    if (data && data.messages) {
        renderHistoryChat(data.messages);
    }
}

export function editAndResubmit(btn) {
    const bubble = btn.closest(".chat-bubble");
    const text = bubble.querySelector(".message-text").textContent;

    // Switch to a live session if one exists
    if (state.liveSessions.length > 0 && (!state.currentSession || state.currentSession.type !== "live")) {
        selectLiveSession(state.liveSessions[0].name, state.liveSessions[0].agent_type);
    }

    // If we're viewing a live session, just populate the input
    if (state.currentSession && state.currentSession.type === "live") {
        document.getElementById("command-input").value = text;
        document.getElementById("command-input").focus();
        showToast("Message copied to input — edit and send");
    } else {
        showToast("No live session available to send to", true);
    }
}
