/* Agent Fleet Dashboard — Client-side JavaScript (SDK edition) */

// ── State ──────────────────────────────────────────────────────────────────

let currentSession = null;       // { type: "live"|"history", name: string }
let sessionWs = null;            // WebSocket for current live session
let fleetWs = null;              // WebSocket for fleet updates
let autoScroll = true;
let liveSessions = [];           // cached live session list

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

    // Auto-scroll detection
    const output = document.getElementById("session-output");
    output.addEventListener("scroll", () => {
        const { scrollTop, scrollHeight, clientHeight } = output;
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
            return;
        }
        const result = await resp.json();
        if (result.error) {
            showToast(result.error, true);
        } else {
            input.value = "";
            showToast(`Sent: ${command}`);
        }
    } catch (e) {
        showToast("Failed to send command", true);
        console.error("Send exception:", e);
    }
}

async function interruptAgent() {
    if (!currentSession || currentSession.type !== "live") {
        showToast("No live session selected", true);
        return;
    }

    try {
        const resp = await fetch(`/api/sessions/live/${encodeURIComponent(currentSession.name)}/interrupt`, {
            method: "POST",
        });
        const result = await resp.json();
        if (result.error) {
            showToast(result.error, true);
        } else {
            showToast("Agent interrupted");
        }
    } catch (e) {
        showToast("Failed to interrupt agent", true);
        console.error("Interrupt exception:", e);
    }
}

async function stopAgent(name) {
    try {
        const resp = await fetch(`/api/sessions/live/${encodeURIComponent(name)}`, {
            method: "DELETE",
        });
        const result = await resp.json();
        if (result.error) {
            showToast(result.error, true);
        } else {
            showToast(`Stopped: ${name}`);
            loadLiveSessions();
        }
    } catch (e) {
        showToast("Failed to stop agent", true);
    }
}

async function launchSession() {
    const dir = document.getElementById("launch-dir").value.trim();

    if (!dir) {
        showToast("Working directory is required", true);
        return;
    }

    try {
        const resp = await fetch("/api/sessions/launch", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ working_dir: dir }),
        });
        const result = await resp.json();
        if (result.error) {
            showToast(result.error, true);
        } else {
            showToast(`Launched: ${result.session_name || result.name}`);
            hideLaunchModal();
            setTimeout(loadLiveSessions, 1000);
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
        const dotClass = s.is_busy ? "active" : "stale";
        const isActive = currentSession && currentSession.type === "live" && currentSession.name === s.name;
        return `<li class="${isActive ? 'active' : ''}" onclick="selectLiveSession('${escapeHtml(s.name)}')">
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

async function selectLiveSession(name) {
    // Close existing WebSocket
    if (sessionWs) {
        sessionWs.close();
        sessionWs = null;
    }

    currentSession = { type: "live", name };

    // Show live view, hide others
    document.getElementById("welcome-screen").style.display = "none";
    document.getElementById("history-session-view").style.display = "none";
    document.getElementById("live-session-view").style.display = "flex";

    // Update header
    document.getElementById("session-name").textContent = name;

    // Clear output
    const output = document.getElementById("session-output");
    output.innerHTML = "";

    // Set up quick action buttons
    renderQuickActions();

    // Highlight in sidebar
    updateSidebarActive();

    // Connect WebSocket for streaming (snapshot will arrive first)
    connectSessionWs(name);
}

async function selectHistorySession(sessionId) {
    if (sessionWs) {
        sessionWs.close();
        sessionWs = null;
    }

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

// ── WebSocket Connections ──────────────────────────────────────────────────

function connectSessionWs(name) {
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    const url = `${proto}//${location.host}/ws/session/${encodeURIComponent(name)}`;

    sessionWs = new WebSocket(url);

    sessionWs.onmessage = (event) => {
        const data = JSON.parse(event.data);
        handleSessionEvent(data);
    };

    sessionWs.onclose = () => {
        if (currentSession && currentSession.type === "live" && currentSession.name === name) {
            setTimeout(() => connectSessionWs(name), 3000);
        }
    };

    sessionWs.onerror = () => {
        // Will trigger onclose
    };
}

function handleSessionEvent(data) {
    switch (data.type) {
        case "snapshot":
            // Initial load: populate state and recent messages
            updateSessionStatus(data.status);
            updateSessionSummary(data.summary);
            updateBusyIndicator(data.is_busy);
            updateSessionInfo(data.total_cost_usd, data.session_id);
            if (data.recent_messages) {
                for (const msg of data.recent_messages) {
                    renderEvent(msg);
                }
            }
            break;

        case "text":
            appendOutputBlock("text-block", data.text);
            break;

        case "status":
            updateSessionStatus(data.text);
            break;

        case "summary":
            updateSessionSummary(data.text);
            break;

        case "tool_use":
            appendToolUseBlock(data.tool, data.input, data.tool_use_id);
            break;

        case "tool_result":
            appendToolResultBlock(data.content, data.is_error, data.tool_use_id);
            break;

        case "result":
            appendResultBlock(data);
            updateSessionInfo(data.total_cost_usd, data.session_id);
            updateBusyIndicator(false);
            break;

        case "system":
            // System init messages — update session_id
            if (data.session_id) {
                updateSessionInfo(null, data.session_id);
            }
            break;

        case "error":
            appendOutputBlock("error-block", data.text);
            break;

        case "stream":
            // Partial stream events — currently a no-op in the UI
            break;
    }
}

function renderEvent(msg) {
    // Re-dispatch stored events from the snapshot's recent_messages
    handleSessionEvent(msg);
}

function connectFleetWs() {
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    const url = `${proto}//${location.host}/ws/fleet`;

    fleetWs = new WebSocket(url);

    fleetWs.onmessage = (event) => {
        const data = JSON.parse(event.data);
        if (data.type === "fleet_update") {
            liveSessions = data.sessions;
            renderLiveSessions(data.sessions);
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

function appendOutputBlock(className, text) {
    const output = document.getElementById("session-output");
    const block = document.createElement("div");
    block.className = `output-block ${className}`;
    block.textContent = text;
    output.appendChild(block);
    trimOutput(output);
    scrollIfNeeded(output);
}

function appendToolUseBlock(toolName, input, toolUseId) {
    const output = document.getElementById("session-output");
    const block = document.createElement("div");
    block.className = "output-block tool-use-block";
    if (toolUseId) block.dataset.toolUseId = toolUseId;

    const header = document.createElement("div");
    header.className = "tool-header";
    header.innerHTML = `<span class="tool-icon">&#9881;</span> <strong>${escapeHtml(toolName)}</strong>`;
    header.onclick = () => {
        details.style.display = details.style.display === "none" ? "" : "none";
    };

    const details = document.createElement("pre");
    details.className = "tool-details";
    details.textContent = formatToolInput(toolName, input);
    details.style.display = "none";

    block.appendChild(header);
    block.appendChild(details);
    output.appendChild(block);
    trimOutput(output);
    scrollIfNeeded(output);
}

function formatToolInput(toolName, input) {
    if (!input) return "";
    // Show relevant fields based on tool type
    if (toolName === "Read" && input.file_path) return input.file_path;
    if (toolName === "Write" && input.file_path) return input.file_path;
    if (toolName === "Edit" && input.file_path) return `${input.file_path}\n-${(input.old_string || "").substring(0, 200)}\n+${(input.new_string || "").substring(0, 200)}`;
    if (toolName === "Bash" && input.command) return input.command;
    if (toolName === "Glob" && input.pattern) return input.pattern;
    if (toolName === "Grep" && input.pattern) return `${input.pattern}${input.path ? " in " + input.path : ""}`;
    return JSON.stringify(input, null, 2);
}

function appendToolResultBlock(content, isError, toolUseId) {
    const output = document.getElementById("session-output");
    const block = document.createElement("div");
    block.className = `output-block tool-result-block ${isError ? "tool-error" : ""}`;
    if (toolUseId) block.dataset.toolUseId = toolUseId;

    // Truncate long results
    const displayContent = content && content.length > 2000
        ? content.substring(0, 2000) + "\n... (truncated)"
        : content || "";

    const header = document.createElement("div");
    header.className = "tool-result-header";
    header.innerHTML = isError
        ? '<span class="result-icon error-icon">&#10007;</span> Error'
        : '<span class="result-icon">&#10003;</span> Result';
    header.onclick = () => {
        details.style.display = details.style.display === "none" ? "" : "none";
    };

    const details = document.createElement("pre");
    details.className = "tool-result-content";
    details.textContent = displayContent;
    details.style.display = "none";

    block.appendChild(header);
    block.appendChild(details);
    output.appendChild(block);
    trimOutput(output);
    scrollIfNeeded(output);
}

function appendResultBlock(data) {
    const output = document.getElementById("session-output");
    const block = document.createElement("div");
    block.className = "output-block result-summary-block";

    const parts = [];
    if (data.num_turns) parts.push(`${data.num_turns} turns`);
    if (data.duration_ms) parts.push(`${(data.duration_ms / 1000).toFixed(1)}s`);
    if (data.total_cost_usd != null) parts.push(`$${data.total_cost_usd.toFixed(4)}`);
    if (data.is_error) parts.push("(error)");

    block.textContent = `Done: ${parts.join(" | ")}`;
    output.appendChild(block);
    trimOutput(output);
    scrollIfNeeded(output);
}

function trimOutput(output) {
    while (output.children.length > 2000) {
        output.removeChild(output.firstChild);
    }
}

function scrollIfNeeded(output) {
    if (autoScroll) {
        output.scrollTop = output.scrollHeight;
    }
}

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

function updateBusyIndicator(isBusy) {
    const el = document.getElementById("busy-indicator");
    el.style.display = isBusy ? "" : "none";

    const dot = document.querySelector("#session-status .status-dot");
    if (dot) {
        dot.className = `status-dot ${isBusy ? "busy" : ""}`;
    }
}

function updateSessionInfo(cost, sessionId) {
    const infoEl = document.getElementById("session-info");

    if (cost != null) {
        document.getElementById("session-cost").textContent = `Cost: $${cost.toFixed(4)}`;
    }
    if (sessionId) {
        document.getElementById("session-id-display").textContent = `Session: ${sessionId.substring(0, 12)}...`;
    }

    if (cost != null || sessionId) {
        infoEl.style.display = "";
    }
}

function renderQuickActions() {
    const container = document.getElementById("quick-actions");
    container.innerHTML = `
        <button class="btn btn-small" onclick="sendQuickCommand('/compact')">/compact</button>
        <button class="btn btn-small btn-danger" onclick="stopCurrentAgent()">Stop</button>
    `;
}

function sendQuickCommand(command) {
    document.getElementById("command-input").value = command;
    sendCommand();
}

function stopCurrentAgent() {
    if (currentSession && currentSession.type === "live") {
        stopAgent(currentSession.name);
    }
}

function updateSidebarActive() {
    document.querySelectorAll(".session-list li").forEach(li => li.classList.remove("active"));
    if (liveSessions.length) renderLiveSessions(liveSessions);
}

function editAndResubmit(btn) {
    const bubble = btn.closest(".chat-bubble");
    const text = bubble.querySelector(".message-text").textContent;

    if (liveSessions.length > 0 && (!currentSession || currentSession.type !== "live")) {
        selectLiveSession(liveSessions[0].name);
    }

    if (currentSession && currentSession.type === "live") {
        document.getElementById("command-input").value = text;
        document.getElementById("command-input").focus();
        showToast("Message copied to input — edit and send");
    } else {
        showToast("No live session available to send to", true);
    }
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
