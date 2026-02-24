/* Agent Fleet Dashboard — Entry Point */

import { state } from './state.js';
import { loadLiveSessions, loadHistorySessions } from './api.js';
import { connectFleetWs } from './websocket.js';
import { sendCommand, sendRawKeys, sendModeToggle, sendQuickCommand, sendResetCommand, attachTerminal, killSession, restartSession } from './controls.js';
import { selectLiveSession, selectHistorySession, editAndResubmit } from './sessions.js';
import { showLaunchModal, hideLaunchModal, launchSession, showInfoModal, hideInfoModal, copyInfoCommand } from './modals.js';
import { toggleBrowser, browserNavigateTo, browserNavigateUp } from './browser.js';
import { initSidebarResize } from './sidebar.js';
import { loadSessionNotes, saveNotes, resummarize, toggleNotesEdit, cancelNotesEdit, switchHistoryTab } from './notes.js';
import { loadSessionTags, addTagToSession, removeTagFromSession, showTagDropdown, hideTagDropdown, createTag } from './tags.js';

// ── Expose functions to HTML onclick handlers ─────────────────────────────
window.sendCommand = sendCommand;
window.sendRawKeys = sendRawKeys;
window.sendModeToggle = sendModeToggle;
window.sendQuickCommand = sendQuickCommand;
window.sendResetCommand = sendResetCommand;
window.attachTerminal = attachTerminal;
window.killSession = killSession;
window.restartSession = restartSession;
window.selectLiveSession = selectLiveSession;
window.selectHistorySession = selectHistorySession;
window.editAndResubmit = editAndResubmit;
window.showLaunchModal = showLaunchModal;
window.hideLaunchModal = hideLaunchModal;
window.launchSession = launchSession;
window.showInfoModal = showInfoModal;
window.hideInfoModal = hideInfoModal;
window.copyInfoCommand = copyInfoCommand;
window.toggleBrowser = toggleBrowser;
window.browserNavigateTo = browserNavigateTo;
window.browserNavigateUp = browserNavigateUp;
window.loadSessionNotes = loadSessionNotes;
window.saveNotes = saveNotes;
window.resummarize = resummarize;
window.toggleNotesEdit = toggleNotesEdit;
window.cancelNotesEdit = cancelNotesEdit;
window.switchHistoryTab = switchHistoryTab;
window.loadSessionTags = loadSessionTags;
window.addTagToSession = addTagToSession;
window.removeTagFromSession = removeTagFromSession;
window.showTagDropdown = showTagDropdown;
window.hideTagDropdown = hideTagDropdown;
window.createTag = createTag;

// ── Initialization ────────────────────────────────────────────────────────
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
        state.autoScroll = (scrollHeight - scrollTop - clientHeight) < 50;
    });

    // Sidebar resize handle
    initSidebarResize();
});
