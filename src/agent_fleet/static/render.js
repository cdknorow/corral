/* Rendering functions for session lists, chat history, and status updates */

import { state } from './state.js';
import { escapeHtml } from './utils.js';
import { renderSidebarTagDots } from './tags.js';

function getDotClass(staleness) {
    if (staleness === null || staleness === undefined) return "stale";
    if (staleness < 60) return "active";
    if (staleness < 300) return "recent";
    return "stale";
}

export function renderLiveSessions(sessions) {
    const list = document.getElementById("live-sessions-list");

    if (!sessions.length) {
        list.innerHTML = '<li class="empty-state">No live sessions</li>';
        return;
    }

    list.innerHTML = sessions.map(s => {
        const dotClass = getDotClass(s.staleness_seconds);
        const isActive = state.currentSession && state.currentSession.type === "live" && state.currentSession.name === s.name && state.currentSession.agent_type === s.agent_type;
        const typeTag = s.agent_type && s.agent_type !== "claude" ? ` <span class="badge ${escapeHtml(s.agent_type)}">${escapeHtml(s.agent_type)}</span>` : "";
        return `<li class="${isActive ? 'active' : ''}" onclick="selectLiveSession('${escapeHtml(s.name)}', '${escapeHtml(s.agent_type)}')">
            <span class="session-dot ${dotClass}"></span>
            <span class="session-label">${escapeHtml(s.name)}${typeTag}</span>
        </li>`;
    }).join("");
}

export function renderHistorySessions(sessions) {
    const list = document.getElementById("history-sessions-list");

    if (!sessions.length) {
        list.innerHTML = '<li class="empty-state">No history found</li>';
        return;
    }

    // Show most recent 50
    list.innerHTML = sessions.slice(0, 50).map(s => {
        const label = s.summary || s.session_id;
        const truncated = label.length > 40 ? label.substring(0, 40) + "..." : label;
        const isActive = state.currentSession && state.currentSession.type === "history" && state.currentSession.name === s.session_id;
        const typeTag = s.source_type === "gemini" ? ' <span class="badge gemini">gemini</span>' : "";
        const tagDots = s.tags ? renderSidebarTagDots(s.tags) : "";
        return `<li class="${isActive ? 'active' : ''}" onclick="selectHistorySession('${escapeHtml(s.session_id)}')">
            <span class="session-label" title="${escapeHtml(label)}">${escapeHtml(truncated)}${typeTag}${tagDots}</span>
        </li>`;
    }).join("");
}

export function renderHistoryChat(messages) {
    const container = document.getElementById("history-messages");
    container.innerHTML = "";

    for (const entry of messages) {
        const type = entry.type || "unknown";
        const msg = entry.message || {};
        let content = "";

        if (typeof msg.content === "string") {
            content = msg.content;
        } else if (Array.isArray(msg.content)) {
            content = msg.content
                .filter(b => b.type === "text")
                .map(b => b.text)
                .join("\n");
        }

        if (!content.trim()) continue;

        const bubbleClass = type === "human" ? "human" : "assistant";
        const roleLabel = type === "human" ? "You" : "Assistant";

        const bubble = document.createElement("div");
        bubble.className = `chat-bubble ${bubbleClass}`;
        bubble.innerHTML = `
            <div class="role-label">${roleLabel}</div>
            <div class="message-text">${escapeHtml(content)}</div>
            ${type === "human" ? `<button class="edit-btn" onclick="editAndResubmit(this)">Edit & Resubmit</button>` : ""}
        `;
        container.appendChild(bubble);
    }

    container.scrollTop = container.scrollHeight;
}

export function updateSessionStatus(status) {
    const el = document.getElementById("session-status");
    if (status) {
        el.querySelector(".status-text").textContent = status;
        el.style.display = "";
    }
}

export function updateSessionSummary(summary) {
    const el = document.getElementById("session-summary");
    if (summary) {
        el.querySelector(".summary-text").textContent = summary;
        el.style.display = "";
    } else {
        el.style.display = "none";
    }
}
