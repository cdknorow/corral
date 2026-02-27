/* Quick actions, command sending, mode toggling, and session controls */

import { state, sessionKey } from './state.js';
import { escapeHtml, escapeAttr, showToast } from './utils.js';
import { stopCaptureRefresh } from './capture.js';
import { renderLiveSessions } from './render.js';

export async function sendCommand() {
    if (!state.currentSession || state.currentSession.type !== "live") {
        showToast("No live session selected", true);
        return;
    }

    const input = document.getElementById("command-input");
    const command = input.value.trim();
    if (!command) return;

    try {
        const resp = await fetch(`/api/sessions/live/${encodeURIComponent(state.currentSession.name)}/send`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ command, agent_type: state.currentSession.agent_type }),
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
            const key = sessionKey(state.currentSession);
            if (key) delete state.sessionInputText[key];
            showToast(`Sent: ${command}`);
        }
    } catch (e) {
        showToast("Failed to send command", true);
        console.error("Send exception:", e);
    }
}

export function renderQuickActions() {
    const toolbar = document.getElementById("command-toolbar");
    toolbar.innerHTML = `
        <button class="btn-nav btn-mode" onclick="sendModeToggle('plan')" title="Plan Mode"><svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M4 2h8a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V3a1 1 0 0 1 1-1z"/><line x1="6" y1="5" x2="10" y2="5"/><line x1="6" y1="8" x2="10" y2="8"/><line x1="6" y1="11" x2="8" y2="11"/></svg><span class="btn-label">Plan Mode</span></button>
        <button class="btn-nav btn-mode" onclick="sendModeToggle('auto')" title="Accept Edits"><svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="3.5 8.5 6.5 11.5 12.5 4.5"/></svg><span class="btn-label">Accept Edits</span></button>
        <button class="btn-nav btn-mode" onclick="sendQuickCommand('!')" title="Bash Mode"><svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M2 3h12a1 1 0 0 1 1 1v8a1 1 0 0 1-1 1H2a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1z"/><polyline points="4 7 6 9 4 11"/><line x1="8" y1="11" x2="12" y2="11"/></svg><span class="btn-label">Bash Mode</span></button>
        <span class="toolbar-divider"></span>
        <button class="btn-nav" onclick="sendQuickCommand('${escapeAttr(state.currentCommands.compress || "/compact")}')">
            ${escapeHtml(state.currentCommands.compress || "/compact")}
        </button>
        <button class="btn-nav" onclick="sendQuickCommand('${escapeAttr(state.currentCommands.clear || "/clear")}')">
            ${escapeHtml(state.currentCommands.clear || "/clear")}
        </button>
        <span class="toolbar-divider"></span>
        <button class="btn-nav btn-danger" onclick="sendResetCommand()">Reset</button>
        <span class="toolbar-spacer"></span>
        <button class="btn-nav" onclick="sendRawKeys(['Escape'])" title="Escape">Esc</button>
        <button class="btn-nav" onclick="sendRawKeys(['Up'])" title="Arrow Up">&uarr;</button>
        <button class="btn-nav" onclick="sendRawKeys(['Down'])" title="Arrow Down">&darr;</button>
        <button class="btn-nav btn-enter" onclick="sendRawKeys(['Enter'])" title="Enter">&#9166;</button>
        <button class="btn-nav btn-primary btn-send" onclick="sendCommand()">Send</button>
    `;
}

export async function sendRawKeys(keys) {
    if (!state.currentSession || state.currentSession.type !== "live") {
        showToast("No live session selected", true);
        return;
    }

    try {
        const resp = await fetch(`/api/sessions/live/${encodeURIComponent(state.currentSession.name)}/keys`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ keys, agent_type: state.currentSession ? state.currentSession.agent_type : null }),
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

export async function attachTerminal() {
    if (!state.currentSession || state.currentSession.type !== "live") {
        showToast("No live session selected", true);
        return;
    }

    try {
        const resp = await fetch(`/api/sessions/live/${encodeURIComponent(state.currentSession.name)}/attach`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ agent_type: state.currentSession.agent_type }),
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

export async function killSession() {
    if (!state.currentSession || state.currentSession.type !== "live") {
        showToast("No live session selected", true);
        return;
    }

    if (!confirm(`Kill session "${state.currentSession.name}"? This will terminate the agent.`)) {
        return;
    }

    try {
        const resp = await fetch(`/api/sessions/live/${encodeURIComponent(state.currentSession.name)}/kill`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ agent_type: state.currentSession.agent_type }),
        });
        const result = await resp.json();
        if (result.error) {
            showToast(result.error, true);
        } else {
            const killedName = state.currentSession.name;
            const killedType = state.currentSession.agent_type;
            showToast(`Killed: ${killedName}`);
            stopCaptureRefresh();
            state.currentSession = null;
            document.getElementById("live-session-view").style.display = "none";
            document.getElementById("welcome-screen").style.display = "flex";
            // Remove from cached list and re-render immediately
            state.liveSessions = state.liveSessions.filter(s => !(s.name === killedName && s.agent_type === killedType));
            renderLiveSessions(state.liveSessions);
        }
    } catch (e) {
        showToast("Failed to kill session", true);
        console.error("killSession exception:", e);
    }
}

export async function restartSession() {
    if (!state.currentSession || state.currentSession.type !== "live") {
        showToast("No live session selected", true);
        return;
    }

    const extraFlags = prompt(
        `Restart session "${state.currentSession.name}"?\n\nOptional extra flags (e.g. --chrome):`,
        ""
    );
    if (extraFlags === null) {
        return;
    }

    try {
        showToast(`Restarting ${state.currentSession.name}...`);
        const payload = { agent_type: state.currentSession.agent_type };
        if (extraFlags.trim()) {
            payload.extra_flags = extraFlags.trim();
        }
        const resp = await fetch(`/api/sessions/live/${encodeURIComponent(state.currentSession.name)}/restart`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });
        const result = await resp.json();
        if (result.error) {
            showToast(result.error, true);
        } else {
            showToast(`Restarted: ${state.currentSession.name}`);
        }
    } catch (e) {
        showToast("Failed to restart session", true);
        console.error("restartSession exception:", e);
    }
}

// Claude Code modes cycle via Shift+Tab (BTab in tmux).
// Order: default -> plan -> auto-accept -> default
const MODE_CYCLE = ["default", "plan", "auto"];

function detectCurrentMode() {
    const el = document.getElementById("pane-capture");
    const text = (el.textContent || "").toLowerCase();
    if (text.includes("plan mode")) return "plan";
    if (text.includes("auto-accept") || text.includes("accept edits")) return "auto";
    return "default";
}

export function sendModeToggle(targetMode) {
    const current = detectCurrentMode();
    if (current === targetMode) {
        showToast(`Already in ${targetMode === "plan" ? "Plan" : targetMode === "auto" ? "Accept Edits" : "Base"} mode`);
        return;
    }

    const currentIdx = MODE_CYCLE.indexOf(current);
    const targetIdx = MODE_CYCLE.indexOf(targetMode);
    let presses = (targetIdx - currentIdx + MODE_CYCLE.length) % MODE_CYCLE.length;
    if (presses === 0) presses = MODE_CYCLE.length;

    const keys = Array(presses).fill("BTab");
    sendRawKeys(keys);
}

export function sendQuickCommand(command) {
    document.getElementById("command-input").value = command;
    sendCommand();
}

export function sendResetCommand() {
    const compress = state.currentCommands.compress || "/compact";
    const clear = state.currentCommands.clear || "/clear";
    document.getElementById("command-input").value = compress;
    sendCommand();
    setTimeout(() => {
        document.getElementById("command-input").value = clear;
        sendCommand();
    }, 1000);
}

export function updateSidebarActive() {
    document.querySelectorAll(".session-list li").forEach(li => li.classList.remove("active"));
    if (state.liveSessions.length) renderLiveSessions(state.liveSessions);
}
