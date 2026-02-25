/* Modal management: launch and info dialogs */

import { state } from './state.js';
import { showToast, escapeHtml } from './utils.js';
import { loadLiveSessions } from './api.js';

export function showLaunchModal() {
    document.getElementById("launch-modal").style.display = "flex";
    document.getElementById("launch-dir").focus();
}

export function hideLaunchModal() {
    document.getElementById("launch-modal").style.display = "none";
}

export async function launchSession() {
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
            setTimeout(loadLiveSessions, 2000);
        }
    } catch (e) {
        showToast("Failed to launch session", true);
    }
}

export async function showInfoModal() {
    if (!state.currentSession || state.currentSession.type !== "live") {
        showToast("No live session selected", true);
        return;
    }

    const name = state.currentSession.name;
    const agentType = state.currentSession.agent_type || "";

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
        document.getElementById("info-git-branch").textContent = info.git_branch || "—";
        const commitHash = info.git_commit_hash ? info.git_commit_hash.substring(0, 8) : "";
        const commitSubject = info.git_commit_subject || "";
        document.getElementById("info-git-commit").textContent = commitHash ? `${commitHash} ${commitSubject}` : "—";

        document.getElementById("info-modal").style.display = "flex";
    } catch (e) {
        showToast("Failed to load session info", true);
        console.error("showInfoModal exception:", e);
    }
}

export function hideInfoModal() {
    document.getElementById("info-modal").style.display = "none";
}

export function copyInfoCommand() {
    const text = document.getElementById("info-tmux-command").textContent;
    navigator.clipboard.writeText(text).then(() => {
        showToast("Copied to clipboard");
    }).catch(() => {
        showToast("Failed to copy", true);
    });
}

// Close modals on outside click
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

// Close modals on Escape
document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
        hideLaunchModal();
        hideInfoModal();
    }
});
