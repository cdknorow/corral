/* Agent Fleet Dashboard — Client-side JavaScript */

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

    // Sidebar resize handle
    initSidebarResize();
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

async function loadLiveSessionDetail(name, agentType) {
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
            body: JSON.stringify({ command, agent_type: currentSession.agent_type }),
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

// Detect separator lines (horizontal rules made of box-drawing chars like ─ ━ ═)
function isSeparatorLine(line) {
    const stripped = line.trim();
    if (stripped.length < 4) return false;
    return /^[─━═╌╍┄┅┈┉\-]+$/.test(stripped);
}

// Detect user prompt lines (❯, >, $)
function isUserPromptLine(line) {
    return /^\s*[❯›>$]\s+\S/.test(line);
}

// Detect code fence markers from Claude Code output (e.g. "  1 │ ...", tool headers)
const CODE_FENCE_RE = /^(\s*\d+\s*[│|])/;
// Diff lines: "  185 -  old code" or "  185 +  new code" (number then +/-)
const DIFF_ADD_RE = /^(\s*\d+\s*\+)/;
const DIFF_DEL_RE = /^(\s*\d+\s*-)/;
// Diff summary line: "Added N lines, removed M lines"
const DIFF_SUMMARY_RE = /^\s*Added \d+ lines?,\s*removed \d+ lines?/;
const TOOL_HEADER_RE = /^⏺\s+(Read|Write|Edit|Bash|Glob|Grep|NotebookEdit|Task)\b/;
const TOOL_RESULT_RE = /^\s*⎿\s*/;

// Syntax highlighting patterns applied inside code lines
const SYNTAX_RULES = [
    // Comments (# ..., // ..., /* ... */, <!-- ... -->)
    { re: /(#[^!].*|\/\/.*|\/\*.*?\*\/|<!--.*?-->)/, cls: "sh-comment" },
    // Strings (double-quoted and single-quoted)
    { re: /("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'|`(?:[^`\\]|\\.)*`)/, cls: "sh-string" },
    // Keywords (common across Python, JS, TS, Go, Rust, shell, etc.)
    { re: /\b(function|const|let|var|return|if|else|elif|for|while|class|def|import|from|export|default|async|await|try|catch|except|finally|raise|throw|new|this|self|yield|match|case|fn|pub|mod|use|impl|struct|enum|trait|interface|type|extends|implements|package|func|go|defer|select|chan)\b/, cls: "sh-keyword" },
    // Built-in values
    { re: /\b(true|false|True|False|null|None|undefined|nil)\b/, cls: "sh-builtin" },
    // Numbers
    { re: /\b(\d+\.?\d*(?:e[+-]?\d+)?|0x[0-9a-fA-F]+|0b[01]+|0o[0-7]+)\b/, cls: "sh-number" },
    // Decorators / annotations
    { re: /(@\w+)/, cls: "sh-decorator" },
];

function highlightCodeLine(text) {
    // Build a list of {start, end, cls} spans, non-overlapping
    const spans = [];

    for (const rule of SYNTAX_RULES) {
        const global = new RegExp(rule.re.source, "g");
        let m;
        while ((m = global.exec(text)) !== null) {
            const start = m.index;
            const end = start + m[0].length;
            // Only add if it doesn't overlap with existing spans
            const overlaps = spans.some(s => start < s.end && end > s.start);
            if (!overlaps) {
                spans.push({ start, end, cls: rule.cls });
            }
        }
    }

    if (spans.length === 0) return null; // no highlighting needed

    spans.sort((a, b) => a.start - b.start);

    const frag = document.createDocumentFragment();
    let pos = 0;
    for (const span of spans) {
        if (span.start > pos) {
            frag.appendChild(document.createTextNode(text.slice(pos, span.start)));
        }
        const el = document.createElement("span");
        el.className = span.cls;
        el.textContent = text.slice(span.start, span.end);
        frag.appendChild(el);
        pos = span.end;
    }
    if (pos < text.length) {
        frag.appendChild(document.createTextNode(text.slice(pos)));
    }
    return frag;
}

function renderCaptureText(el, text) {
    el.innerHTML = "";
    const lines = text.split("\n");
    let inUserBlock = false;
    let inCodeBlock = false;

    for (let i = 0; i < lines.length; i++) {
        const line = lines[i];
        const div = document.createElement("div");
        div.className = "capture-line";

        const diffAddMatch = line.match(DIFF_ADD_RE);
        const diffDelMatch = !diffAddMatch && line.match(DIFF_DEL_RE);
        const isDiffSummary = DIFF_SUMMARY_RE.test(line);
        const isNumberedCode = !diffAddMatch && !diffDelMatch && CODE_FENCE_RE.test(line);
        const isToolHeader = TOOL_HEADER_RE.test(line);
        const isToolResult = TOOL_RESULT_RE.test(line);

        if (isSeparatorLine(line)) {
            const prevIsUser = i > 0 && isUserPromptLine(lines[i - 1]);
            const nextIsUser = i < lines.length - 1 && isUserPromptLine(lines[i + 1]);
            if (prevIsUser || nextIsUser || inUserBlock) {
                div.classList.add("capture-separator");
                inUserBlock = nextIsUser;
            }
            inCodeBlock = false;
        } else if (isUserPromptLine(line)) {
            div.classList.add("capture-user-input");
            inUserBlock = true;
            inCodeBlock = false;
        } else if (inUserBlock && line.trim() !== "") {
            div.classList.add("capture-user-input");
        } else if (isDiffSummary) {
            div.classList.add("capture-diff-summary");
            inUserBlock = false;
            inCodeBlock = false;
        } else if (diffAddMatch) {
            // Diff addition: "  185 +  new code"
            div.classList.add("capture-diff-add");
            inUserBlock = false;
            inCodeBlock = false;
            const gutter = diffAddMatch[1];
            const code = line.slice(gutter.length);
            const gutterSpan = document.createElement("span");
            gutterSpan.className = "sh-diff-gutter-add";
            gutterSpan.textContent = gutter;
            div.appendChild(gutterSpan);
            const highlighted = highlightCodeLine(code);
            if (highlighted) {
                div.appendChild(highlighted);
            } else {
                div.appendChild(document.createTextNode(code));
            }
            el.appendChild(div);
            continue;
        } else if (diffDelMatch) {
            // Diff deletion: "  185 -  old code"
            div.classList.add("capture-diff-del");
            inUserBlock = false;
            inCodeBlock = false;
            const gutter = diffDelMatch[1];
            const code = line.slice(gutter.length);
            const gutterSpan = document.createElement("span");
            gutterSpan.className = "sh-diff-gutter-del";
            gutterSpan.textContent = gutter;
            div.appendChild(gutterSpan);
            div.appendChild(document.createTextNode(code));
            el.appendChild(div);
            continue;
        } else if (isToolHeader) {
            div.classList.add("capture-tool-header");
            inUserBlock = false;
            inCodeBlock = false;
        } else if (isToolResult) {
            div.classList.add("capture-tool-result");
            inUserBlock = false;
        } else if (isNumberedCode) {
            div.classList.add("capture-code");
            inUserBlock = false;
            inCodeBlock = true;
            // Highlight the code portion after the line number gutter
            const match = line.match(CODE_FENCE_RE);
            const gutter = match[1];
            const code = line.slice(gutter.length);
            const gutterSpan = document.createElement("span");
            gutterSpan.className = "sh-gutter";
            gutterSpan.textContent = gutter;
            div.appendChild(gutterSpan);
            const highlighted = highlightCodeLine(code);
            if (highlighted) {
                div.appendChild(highlighted);
            } else {
                div.appendChild(document.createTextNode(code));
            }
            el.appendChild(div);
            continue;
        } else {
            if (inUserBlock && line.trim() === "") {
                inUserBlock = false;
            }
            inCodeBlock = false;
        }

        div.textContent = line;
        el.appendChild(div);
    }
}

async function refreshCapture() {
    if (!currentSession || currentSession.type !== "live") return;

    try {
        let captureUrl = `/api/sessions/live/${encodeURIComponent(currentSession.name)}/capture`;
        if (currentSession.agent_type) captureUrl += `?agent_type=${encodeURIComponent(currentSession.agent_type)}`;
        const resp = await fetch(captureUrl);
        const data = await resp.json();
        const el = document.getElementById("pane-capture");
        const text = data.capture || data.error || "No capture available";

        // Only update if content changed to avoid scroll jank
        if (el._lastCapture !== text) {
            el._lastCapture = text;
            renderCaptureText(el, text);
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
        const isActive = currentSession && currentSession.type === "live" && currentSession.name === s.name && currentSession.agent_type === s.agent_type;
        const typeTag = s.agent_type && s.agent_type !== "claude" ? ` <span class="badge ${escapeHtml(s.agent_type)}">${escapeHtml(s.agent_type)}</span>` : "";
        return `<li class="${isActive ? 'active' : ''}" onclick="selectLiveSession('${escapeHtml(s.name)}', '${escapeHtml(s.agent_type)}')">
            <span class="session-dot ${dotClass}"></span>
            <span class="session-label">${escapeHtml(s.name)}${typeTag}</span>
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
        const typeTag = s.source_type === "gemini" ? ' <span class="badge gemini">gemini</span>' : "";
        return `<li class="${isActive ? 'active' : ''}" onclick="selectHistorySession('${escapeHtml(s.session_id)}')">
            <span class="session-label" title="${escapeHtml(label)}">${escapeHtml(truncated)}${typeTag}</span>
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

    currentSession = { type: "live", name, agent_type: agentType || null };

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

    document.getElementById("history-session-title").textContent = `Session: ${sessionId}`;

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
        <button class="btn btn-small btn-nav" onclick="sendRawKeys(['Escape'])" title="Escape">Esc</button>
        <button class="btn btn-small btn-nav" onclick="sendRawKeys(['Up'])" title="Arrow Up">&uarr;</button>
        <button class="btn btn-small btn-nav" onclick="sendRawKeys(['Down'])" title="Arrow Down">&darr;</button>
        <button class="btn btn-small btn-nav" onclick="sendRawKeys(['Enter'])" title="Enter">&crarr;</button>
        <span class="quick-actions-divider"></span>
        <button class="btn btn-small btn-mode" onclick="sendModeToggle('plan')">Plan Mode</button>
        <button class="btn btn-small btn-mode" onclick="sendModeToggle('auto')">Accept Edits</button>
        <span class="quick-actions-divider"></span>
        <button class="btn btn-small" onclick="sendQuickCommand('${escapeAttr(currentCommands.compress || "/compact")}')">
            ${escapeHtml(currentCommands.compress || "/compact")}
        </button>
        <button class="btn btn-small btn-warning" onclick="sendQuickCommand('${escapeAttr(currentCommands.clear || "/clear")}')">
            ${escapeHtml(currentCommands.clear || "/clear")}
        </button>
        <button class="btn btn-small btn-danger" onclick="sendResetCommand()">Reset</button>
    `;
}

async function sendRawKeys(keys) {
    if (!currentSession || currentSession.type !== "live") {
        showToast("No live session selected", true);
        return;
    }

    try {
        const resp = await fetch(`/api/sessions/live/${encodeURIComponent(currentSession.name)}/keys`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ keys, agent_type: currentSession ? currentSession.agent_type : null }),
        });
        const result = await resp.json();
        if (result.error) {
            showToast(result.error, true);
        } else {
            showToast(`Sent: ${keys.join(" + ")}`);
        }
    } catch (e) {
        showToast("Failed to send keys", true);
        console.error("sendRawKeys exception:", e);
    }
}

async function attachTerminal() {
    if (!currentSession || currentSession.type !== "live") {
        showToast("No live session selected", true);
        return;
    }

    try {
        const resp = await fetch(`/api/sessions/live/${encodeURIComponent(currentSession.name)}/attach`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ agent_type: currentSession.agent_type }),
        });
        const result = await resp.json();
        if (result.error) {
            showToast(result.error, true);
        } else {
            showToast("Terminal opened");
        }
    } catch (e) {
        showToast("Failed to open terminal", true);
        console.error("attachTerminal exception:", e);
    }
}

async function killSession() {
    if (!currentSession || currentSession.type !== "live") {
        showToast("No live session selected", true);
        return;
    }

    if (!confirm(`Kill session "${currentSession.name}"? This will terminate the agent.`)) {
        return;
    }

    try {
        const resp = await fetch(`/api/sessions/live/${encodeURIComponent(currentSession.name)}/kill`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ agent_type: currentSession.agent_type }),
        });
        const result = await resp.json();
        if (result.error) {
            showToast(result.error, true);
        } else {
            const killedName = currentSession.name;
            const killedType = currentSession.agent_type;
            showToast(`Killed: ${killedName}`);
            stopCaptureRefresh();
            currentSession = null;
            document.getElementById("live-session-view").style.display = "none";
            document.getElementById("welcome-screen").style.display = "flex";
            // Remove from cached list and re-render immediately
            liveSessions = liveSessions.filter(s => !(s.name === killedName && s.agent_type === killedType));
            renderLiveSessions(liveSessions);
        }
    } catch (e) {
        showToast("Failed to kill session", true);
        console.error("killSession exception:", e);
    }
}

// Claude Code modes cycle via Shift+Tab (BTab in tmux).
// Order: default → plan → auto-accept → default
// We detect the current mode from the capture and send the right number of BTab presses.
const MODE_CYCLE = ["default", "plan", "auto"];

function detectCurrentMode() {
    const el = document.getElementById("pane-capture");
    const text = (el.textContent || "").toLowerCase();
    // Claude Code status bar shows the current mode
    if (text.includes("plan mode")) return "plan";
    if (text.includes("auto-accept") || text.includes("accept edits")) return "auto";
    return "default";
}

function sendModeToggle(targetMode) {
    const current = detectCurrentMode();
    if (current === targetMode) {
        showToast(`Already in ${targetMode === "plan" ? "Plan" : "Accept Edits"} mode`);
        return;
    }

    const currentIdx = MODE_CYCLE.indexOf(current);
    const targetIdx = MODE_CYCLE.indexOf(targetMode);
    // Calculate how many BTab presses to cycle from current to target
    let presses = (targetIdx - currentIdx + MODE_CYCLE.length) % MODE_CYCLE.length;
    if (presses === 0) presses = MODE_CYCLE.length;

    const keys = Array(presses).fill("BTab");
    sendRawKeys(keys);
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

// ── Sidebar Resize ─────────────────────────────────────────────────────────

function initSidebarResize() {
    const handle = document.getElementById("sidebar-resize-handle");
    const sidebar = document.querySelector(".sidebar");

    let dragging = false;

    handle.addEventListener("mousedown", (e) => {
        e.preventDefault();
        dragging = true;
        handle.classList.add("dragging");
        document.body.style.cursor = "col-resize";
        document.body.style.userSelect = "none";
    });

    document.addEventListener("mousemove", (e) => {
        if (!dragging) return;
        const newWidth = Math.min(Math.max(e.clientX, 140), window.innerWidth * 0.5);
        sidebar.style.width = newWidth + "px";
    });

    document.addEventListener("mouseup", () => {
        if (!dragging) return;
        dragging = false;
        handle.classList.remove("dragging");
        document.body.style.cursor = "";
        document.body.style.userSelect = "";
    });
}

// ── Modal ──────────────────────────────────────────────────────────────────

function showLaunchModal() {
    document.getElementById("launch-modal").style.display = "flex";
    document.getElementById("launch-dir").focus();
}

function hideLaunchModal() {
    document.getElementById("launch-modal").style.display = "none";
}

async function showInfoModal() {
    if (!currentSession || currentSession.type !== "live") {
        showToast("No live session selected", true);
        return;
    }

    const name = currentSession.name;
    const agentType = currentSession.agent_type || "";

    try {
        let url = `/api/sessions/live/${encodeURIComponent(name)}/info`;
        if (agentType) url += `?agent_type=${encodeURIComponent(agentType)}`;
        const resp = await fetch(url);
        const info = await resp.json();

        if (info.error) {
            showToast(info.error, true);
            return;
        }

        document.getElementById("info-agent-name").textContent = info.agent_name || "";
        document.getElementById("info-agent-type").textContent = info.agent_type || "";
        document.getElementById("info-tmux-session").textContent = info.tmux_session_name || "";
        document.getElementById("info-tmux-command").textContent = info.tmux_command || "";
        document.getElementById("info-working-dir").textContent = info.working_directory || "";
        document.getElementById("info-log-path").textContent = info.log_path || "";
        document.getElementById("info-pane-title").textContent = info.pane_title || "";

        document.getElementById("info-modal").style.display = "flex";
    } catch (e) {
        showToast("Failed to load session info", true);
        console.error("showInfoModal exception:", e);
    }
}

function hideInfoModal() {
    document.getElementById("info-modal").style.display = "none";
}

function copyInfoCommand() {
    const text = document.getElementById("info-tmux-command").textContent;
    navigator.clipboard.writeText(text).then(() => {
        showToast("Copied to clipboard");
    }).catch(() => {
        showToast("Failed to copy", true);
    });
}

// Close modal on outside click
document.addEventListener("click", (e) => {
    const launchModal = document.getElementById("launch-modal");
    const infoModal = document.getElementById("info-modal");
    if (e.target === launchModal) {
        hideLaunchModal();
    }
    if (e.target === infoModal) {
        hideInfoModal();
    }
});

// Close modal on Escape
document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
        hideLaunchModal();
        hideInfoModal();
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
