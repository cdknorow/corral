/* Claude Fleet Web Dashboard — Client-side JavaScript */

// ── State ──────────────────────────────────────────────────────────────────

let currentSession = null;       // { type: "live"|"history", name: string }
let fleetWs = null;              // WebSocket for fleet updates
let captureInterval = null;      // interval ID for auto-refreshing capture
let autoScroll = true;
let liveSessions = [];           // cached live session list
let currentCommands = {};        // commands for current session's agent type

const CAPTURE_REFRESH_MS = 2000; // refresh capture every 2 seconds

// ── Initialization ─────────────────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", () => {
    loadLiveSessions();
    loadHistorySessions();
    connectFleetWs();

    // Enter key in command input
    document.getElementById("command-input").addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
            e.preventDefault();
            sendCommand();
        }
    });

    // Auto-scroll detection for capture pane
    const capture = document.getElementById("pane-capture");
    capture.addEventListener("scroll", () => {
        const { scrollTop, scrollHeight, clientHeight } = capture;
        autoScroll = (scrollHeight - scrollTop - clientHeight) < 50;
    });
});

// ── REST API Calls ─────────────────────────────────────────────────────────

async function loadLiveSessions() {
    try {
        const resp = await fetch("/api/sessions/live");
        liveSessions = await resp.json();
        renderLiveSessions(liveSessions);
    } catch (e) {
        console.error("Failed to load live sessions:", e);
    }
}

async function loadHistorySessions() {
    try {
        const resp = await fetch("/api/sessions/history");
        const sessions = await resp.json();
        renderHistorySessions(sessions);
    } catch (e) {
        console.error("Failed to load history sessions:", e);
    }
}

async function loadLiveSessionDetail(name) {
    try {
        const resp = await fetch(`/api/sessions/live/${encodeURIComponent(name)}`);
        return await resp.json();
    } catch (e) {
        console.error("Failed to load session detail:", e);
        return null;
    }
}

async function loadHistoryMessages(sessionId) {
    try {
        const resp = await fetch(`/api/sessions/history/${encodeURIComponent(sessionId)}`);
        return await resp.json();
    } catch (e) {
        console.error("Failed to load history messages:", e);
        return null;
    }
}

async function sendCommand() {
    if (!currentSession || currentSession.type !== "live") {
        showToast("No live session selected", true);
        return;
    }

    const input = document.getElementById("command-input");
    const command = input.value.trim();
    if (!command) return;

    try {
        const resp = await fetch(`/api/sessions/live/${encodeURIComponent(currentSession.name)}/send`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ command }),
        });
        if (!resp.ok) {
            const text = await resp.text();
            showToast(`Server error ${resp.status}: ${text}`, true);
            console.error("Send failed:", resp.status, text);
            return;
        }
        const result = await resp.json();
        if (result.error) {
            showToast(result.error, true);
            console.error("Send error:", result.error);
        } else {
            input.value = "";
            showToast(`Sent: ${command}`);
        }
    } catch (e) {
        showToast("Failed to send command", true);
        console.error("Send exception:", e);
    }
}

async function refreshCapture() {
    if (!currentSession || currentSession.type !== "live") return;

    try {
        const resp = await fetch(`/api/sessions/live/${encodeURIComponent(currentSession.name)}/capture`);
        const data = await resp.json();
        const el = document.getElementById("pane-capture");
        const text = data.capture || data.error || "No capture available";

        // Only update if content changed to avoid scroll jank
        if (el.textContent !== text) {
            el.textContent = text;
            if (autoScroll) {
                el.scrollTop = el.scrollHeight;
            }
        }
    } catch (e) {
        console.error("Failed to refresh capture:", e);
    }
}

function startCaptureRefresh() {
    stopCaptureRefresh();
    refreshCapture();
    captureInterval = setInterval(refreshCapture, CAPTURE_REFRESH_MS);
}

function stopCaptureRefresh() {
    if (captureInterval) {
        clearInterval(captureInterval);
        captureInterval = null;
    }
}

async function launchSession() {
    const dir = document.getElementById("launch-dir").value.trim();
    const type = document.getElementById("launch-type").value;

    if (!dir) {
        showToast("Working directory is required", true);
        return;
    }

    try {
        const resp = await fetch("/api/sessions/launch", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ working_dir: dir, agent_type: type }),
        });
        const result = await resp.json();
        if (result.error) {
            showToast(result.error, true);
        } else {
            showToast(`Launched: ${result.session_name}`);
            hideLaunchModal();
            // Reload sessions after short delay
            setTimeout(loadLiveSessions, 2000);
        }
    } catch (e) {
        showToast("Failed to launch session", true);
    }
}

// ── Rendering ──────────────────────────────────────────────────────────────

function renderLiveSessions(sessions) {
    const list = document.getElementById("live-sessions-list");

    if (!sessions.length) {
        list.innerHTML = '<li class="empty-state">No live sessions</li>';
        return;
    }

    list.innerHTML = sessions.map(s => {
        const dotClass = getDotClass(s.staleness_seconds);
        const isActive = currentSession && currentSession.type === "live" && currentSession.name === s.name;
        return `<li class="${isActive ? 'active' : ''}" onclick="selectLiveSession('${escapeHtml(s.name)}', '${escapeHtml(s.agent_type)}')">
            <span class="session-dot ${dotClass}"></span>
            <span class="session-label">${escapeHtml(s.name)}</span>
        </li>`;
    }).join("");
}

function renderHistorySessions(sessions) {
    const list = document.getElementById("history-sessions-list");

    if (!sessions.length) {
        list.innerHTML = '<li class="empty-state">No history found</li>';
        return;
    }

    // Show most recent 50
    list.innerHTML = sessions.slice(0, 50).map(s => {
        const label = s.summary || s.session_id;
        const truncated = label.length > 40 ? label.substring(0, 40) + "..." : label;
        const isActive = currentSession && currentSession.type === "history" && currentSession.name === s.session_id;
        return `<li class="${isActive ? 'active' : ''}" onclick="selectHistorySession('${escapeHtml(s.session_id)}')">
            <span class="session-label" title="${escapeHtml(label)}">${escapeHtml(truncated)}</span>
        </li>`;
    }).join("");
}

function renderHistoryChat(messages) {
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

// ── Session Selection ──────────────────────────────────────────────────────

async function selectLiveSession(name, agentType) {
    stopCaptureRefresh();

    currentSession = { type: "live", name };

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
    const detail = await loadLiveSessionDetail(name);
    if (detail) {
        updateSessionStatus(detail.status);
        updateSessionSummary(detail.summary);

        // Show initial pane capture
        if (detail.pane_capture) {
            document.getElementById("pane-capture").textContent = detail.pane_capture;
        }
    }

    // Set up quick action buttons
    const agent = liveSessions.find(s => s.name === name);
    currentCommands = (agent && agent.commands) || { compress: "/compact", clear: "/clear" };
    renderQuickActions();

    // Highlight in sidebar
    updateSidebarActive();

    // Start auto-refreshing capture
    startCaptureRefresh();
}

async function selectHistorySession(sessionId) {
    stopCaptureRefresh();

    currentSession = { type: "history", name: sessionId };

    document.getElementById("welcome-screen").style.display = "none";
    document.getElementById("live-session-view").style.display = "none";
    document.getElementById("history-session-view").style.display = "flex";

    document.getElementById("history-session-title").textContent = `Session: ${sessionId.substring(0, 12)}...`;

    updateSidebarActive();

    const data = await loadHistoryMessages(sessionId);
    if (data && data.messages) {
        renderHistoryChat(data.messages);
    }
}

// ── WebSocket Connection (fleet-wide updates only) ─────────────────────────

function connectFleetWs() {
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    const url = `${proto}//${location.host}/ws/fleet`;

    fleetWs = new WebSocket(url);

    fleetWs.onmessage = (event) => {
        const data = JSON.parse(event.data);
        if (data.type === "fleet_update") {
            liveSessions = data.sessions;
            renderLiveSessions(data.sessions);

            // Update status/summary if we're viewing a live session
            if (currentSession && currentSession.type === "live") {
                const s = data.sessions.find(s => s.name === currentSession.name);
                if (s) {
                    updateSessionStatus(s.status);
                    updateSessionSummary(s.summary);
                }
            }
        }
    };

    fleetWs.onclose = () => {
        setTimeout(connectFleetWs, 5000);
    };

    fleetWs.onerror = () => {
        // Will trigger onclose
    };
}

// ── UI Helpers ─────────────────────────────────────────────────────────────

function updateSessionStatus(status) {
    const el = document.getElementById("session-status");
    if (status) {
        el.querySelector(".status-text").textContent = status;
        el.style.display = "";
    }
}

function updateSessionSummary(summary) {
    const el = document.getElementById("session-summary");
    if (summary) {
        el.querySelector(".summary-text").textContent = summary;
        el.style.display = "";
    } else {
        el.style.display = "none";
    }
}

function renderQuickActions() {
    const container = document.getElementById("quick-actions");
    container.innerHTML = `
        <button class="btn btn-small" onclick="sendQuickCommand('${escapeAttr(currentCommands.compress || "/compact")}')">
            ${escapeHtml(currentCommands.compress || "/compact")}
        </button>
        <button class="btn btn-small btn-warning" onclick="sendQuickCommand('${escapeAttr(currentCommands.clear || "/clear")}')">
            ${escapeHtml(currentCommands.clear || "/clear")}
        </button>
        <button class="btn btn-small btn-danger" onclick="sendResetCommand()">Reset</button>
    `;
}

function sendQuickCommand(command) {
    document.getElementById("command-input").value = command;
    sendCommand();
}

function sendResetCommand() {
    const compress = currentCommands.compress || "/compact";
    const clear = currentCommands.clear || "/clear";
    // Send compress first, then clear after a delay
    document.getElementById("command-input").value = compress;
    sendCommand();
    setTimeout(() => {
        document.getElementById("command-input").value = clear;
        sendCommand();
    }, 1000);
}

function updateSidebarActive() {
    document.querySelectorAll(".session-list li").forEach(li => li.classList.remove("active"));
    // Re-render will set active class
    if (liveSessions.length) renderLiveSessions(liveSessions);
}

function editAndResubmit(btn) {
    const bubble = btn.closest(".chat-bubble");
    const text = bubble.querySelector(".message-text").textContent;

    // Switch to a live session if one exists
    if (liveSessions.length > 0 && (!currentSession || currentSession.type !== "live")) {
        selectLiveSession(liveSessions[0].name, liveSessions[0].agent_type);
    }

    // If we're viewing a live session, just populate the input
    if (currentSession && currentSession.type === "live") {
        document.getElementById("command-input").value = text;
        document.getElementById("command-input").focus();
        showToast("Message copied to input — edit and send");
    } else {
        showToast("No live session available to send to", true);
    }
}

function getDotClass(staleness) {
    if (staleness === null || staleness === undefined) return "stale";
    if (staleness < 60) return "active";
    if (staleness < 300) return "recent";
    return "stale";
}

// ── Modal ──────────────────────────────────────────────────────────────────

function showLaunchModal() {
    document.getElementById("launch-modal").style.display = "flex";
    document.getElementById("launch-dir").focus();
}

function hideLaunchModal() {
    document.getElementById("launch-modal").style.display = "none";
}

// Close modal on outside click
document.addEventListener("click", (e) => {
    const modal = document.getElementById("launch-modal");
    if (e.target === modal) {
        hideLaunchModal();
    }
});

// Close modal on Escape
document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
        hideLaunchModal();
    }
});

// ── Toast ──────────────────────────────────────────────────────────────────

function showToast(message, isError = false) {
    const toast = document.createElement("div");
    toast.className = `toast ${isError ? "error" : ""}`;
    toast.textContent = message;
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), 3000);
}

// ── Utilities ──────────────────────────────────────────────────────────────

function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
}

function escapeAttr(str) {
    return str.replace(/'/g, "\\'").replace(/"/g, "&quot;");
}
