/* Agent notes — CRUD and rendering for user-added notes in the sidebar */

import { state } from './state.js';
import { escapeHtml, showToast } from './utils.js';

export async function loadAgentNotes(agentName) {
    if (!agentName) return;
    try {
        const resp = await fetch(`/api/sessions/live/${encodeURIComponent(agentName)}/notes`);
        state.currentAgentNotes = await resp.json();
    } catch (e) {
        state.currentAgentNotes = [];
    }
    renderNotesList();
}

export async function addAgentNote() {
    if (!state.currentSession || state.currentSession.type !== 'live') return;
    const input = document.getElementById('note-bar-input');
    const content = input.value.trim();
    if (!content) return;

    try {
        await fetch(`/api/sessions/live/${encodeURIComponent(state.currentSession.name)}/notes`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ content }),
        });
        input.value = '';
        await loadAgentNotes(state.currentSession.name);
    } catch (e) {
        showToast('Failed to add note', true);
    }
}

export async function deleteAgentNote(noteId) {
    if (!state.currentSession || state.currentSession.type !== 'live') return;
    try {
        await fetch(`/api/sessions/live/${encodeURIComponent(state.currentSession.name)}/notes/${noteId}`, {
            method: 'DELETE',
        });
        await loadAgentNotes(state.currentSession.name);
    } catch (e) {
        showToast('Failed to delete note', true);
    }
}

export function editAgentNote(noteId, spanEl) {
    if (!state.currentSession || state.currentSession.type !== 'live') return;
    const original = spanEl.textContent;
    spanEl.contentEditable = 'true';
    spanEl.focus();

    const range = document.createRange();
    range.selectNodeContents(spanEl);
    const sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(range);

    const finish = async () => {
        spanEl.contentEditable = 'false';
        const newContent = spanEl.textContent.trim();
        if (!newContent || newContent === original) {
            spanEl.textContent = original;
            return;
        }
        try {
            await fetch(`/api/sessions/live/${encodeURIComponent(state.currentSession.name)}/notes/${noteId}`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ content: newContent }),
            });
            await loadAgentNotes(state.currentSession.name);
        } catch (e) {
            spanEl.textContent = original;
            showToast('Failed to update note', true);
        }
    };

    spanEl.addEventListener('blur', finish, { once: true });
    spanEl.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            spanEl.blur();
        } else if (e.key === 'Escape') {
            spanEl.textContent = original;
            spanEl.blur();
        }
    });
}

export function renderNotesList() {
    const list = document.getElementById('note-bar-list');
    const countEl = document.getElementById('note-bar-count');
    if (!list) return;

    const notes = state.currentAgentNotes || [];

    if (countEl) {
        countEl.textContent = notes.length > 0 ? notes.length : '';
    }

    if (notes.length === 0) {
        list.innerHTML = '<div class="note-empty">No notes yet</div>';
        return;
    }

    list.innerHTML = notes.map(n => `
        <div class="note-item" data-note-id="${n.id}">
            <span class="note-content" ondblclick="editAgentNote(${n.id}, this)">${escapeHtml(n.content)}</span>
            <button class="note-delete-btn" onclick="deleteAgentNote(${n.id})" title="Delete note">&times;</button>
        </div>`).join('');
}
