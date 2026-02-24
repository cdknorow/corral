/* Session selection and management */

import { state, sessionKey } from './state.js';
import { showToast } from './utils.js';
import { loadLiveSessionDetail, loadHistoryMessages } from './api.js';
import { stopCaptureRefresh, startCaptureRefresh } from './capture.js';
import { updateSessionStatus, updateSessionSummary, renderHistoryChat } from './render.js';
import { renderQuickActions, updateSidebarActive } from './controls.js';
import { loadSessionNotes, switchHistoryTab } from './notes.js';
import { loadSessionTags } from './tags.js';

export async function selectLiveSession(name, agentType) {
    stopCaptureRefresh();

    // Save current input text for the old session
    const input = document.getElementById("command-input");
    const oldKey = sessionKey(state.currentSession);
    if (oldKey) {
        state.sessionInputText[oldKey] = input.value;
    }

    state.currentSession = { type: "live", name, agent_type: agentType || null };

    // Restore input text for the new session
    const newKey = sessionKey(state.currentSession);
    input.value = state.sessionInputText[newKey] || "";
    input.focus();

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

    // Save current input text for the old session
    const input = document.getElementById("command-input");
    const oldKey = sessionKey(state.currentSession);
    if (oldKey) {
        state.sessionInputText[oldKey] = input.value;
    }

    state.currentSession = { type: "history", name: sessionId };

    // Update URL hash for bookmarking
    window.location.hash = '#session/' + sessionId;

    // Restore input text for the new session
    const newKey = sessionKey(state.currentSession);
    input.value = state.sessionInputText[newKey] || "";

    document.getElementById("welcome-screen").style.display = "none";
    document.getElementById("live-session-view").style.display = "none";
    document.getElementById("history-session-view").style.display = "flex";

    document.getElementById("history-session-title").textContent = `Session: ${sessionId}`;
    document.getElementById("history-session-id").textContent = sessionId;

    updateSidebarActive();

    // Reset to chat tab
    switchHistoryTab('chat');

    const data = await loadHistoryMessages(sessionId);
    if (data && data.messages) {
        renderHistoryChat(data.messages);
    }

    // Load notes and tags in parallel
    loadSessionNotes(sessionId);
    loadSessionTags(sessionId);
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
