/* History tabs — read-only rendering of Activity, Tasks, and Agent Notes for historical sessions */

import { state } from './state.js';

// Re-use tool icon/filter definitions from agentic_state.js
const TOOL_ICONS = {
    Read:       { char: 'R', cls: 'tool-read' },
    Write:      { char: 'W', cls: 'tool-write' },
    Edit:       { char: 'E', cls: 'tool-edit' },
    Bash:       { char: '$', cls: 'tool-bash' },
    Grep:       { char: '?', cls: 'tool-grep' },
    Glob:       { char: '*', cls: 'tool-glob' },
    WebFetch:   { char: 'F', cls: 'tool-web' },
    WebSearch:  { char: 'S', cls: 'tool-web' },
    TaskCreate: { char: 'T', cls: 'tool-task' },
    TaskUpdate: { char: 'T', cls: 'tool-task' },
    TaskList:   { char: 'T', cls: 'tool-task' },
    TaskGet:    { char: 'T', cls: 'tool-task' },
    Task:       { char: 'A', cls: 'tool-agent' },
};

const FILTER_GROUPS = [
    { key: 'read',   label: 'R', title: 'Read',          cls: 'tool-read',   match: ev => ev.tool_name === 'Read' },
    { key: 'write',  label: 'W', title: 'Write',         cls: 'tool-write',  match: ev => ev.tool_name === 'Write' },
    { key: 'edit',   label: 'E', title: 'Edit',          cls: 'tool-edit',   match: ev => ev.tool_name === 'Edit' },
    { key: 'bash',   label: '$', title: 'Bash',          cls: 'tool-bash',   match: ev => ev.tool_name === 'Bash' },
    { key: 'search', label: '?', title: 'Grep / Glob',   cls: 'tool-grep',   match: ev => ev.tool_name === 'Grep' || ev.tool_name === 'Glob' },
    { key: 'web',    label: 'W', title: 'Web',           cls: 'tool-web',    match: ev => ev.tool_name === 'WebFetch' || ev.tool_name === 'WebSearch' },
    { key: 'task',   label: 'T', title: 'Tasks',         cls: 'tool-task',   match: ev => ['TaskCreate','TaskUpdate','TaskList','TaskGet'].includes(ev.tool_name) },
    { key: 'agent',  label: 'A', title: 'Subagents',     cls: 'tool-agent',  match: ev => ev.tool_name === 'Task' },
    { key: 'status',     label: 'S', title: 'Status',          cls: 'tool-status',     match: ev => ev.event_type === 'status' },
    { key: 'goal',       label: 'G', title: 'Goal',            cls: 'tool-goal',       match: ev => ev.event_type === 'goal' },
    { key: 'confidence', label: 'C', title: 'Confidence',      cls: 'tool-confidence', match: ev => ev.event_type === 'confidence' },
    { key: 'system',     label: '!', title: 'Stop / Notify',   cls: 'tool-stop',       match: ev => ev.event_type === 'stop' || ev.event_type === 'notification' },
    { key: 'pulse',      label: 'P', title: 'Pulse (other)',   cls: 'tool-pulse',      match: ev => ev.event_type && !ev.tool_name && !['status','goal','confidence','stop','notification'].includes(ev.event_type) },
];

// Per-session filter state for history
let historyFilterHidden = new Set();
let historyEvents = [];
let historyTasks = [];
let historyAgentNotes = [];

function escapeAttr(str) {
    return (str || '').replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

function formatTime(isoStr) {
    if (!isoStr) return '';
    try {
        const d = new Date(isoStr);
        return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    } catch {
        return '';
    }
}

// Known pulse event types — add new PULSE:<TYPE> entries here
const PULSE_ICONS = {
    status:       { char: 'S', cls: 'tool-status',     title: 'Status' },
    goal:         { char: 'G', cls: 'tool-goal',       title: 'Goal' },
    confidence:   { char: 'C', cls: 'tool-confidence', title: 'Confidence' },
    stop:         { char: '!', cls: 'tool-stop',       title: 'Stop' },
    notification: { char: 'N', cls: 'tool-notification', title: 'Notification' },
};

function getToolIcon(toolName, eventType) {
    // Check pulse event types first
    const pulse = PULSE_ICONS[eventType];
    if (pulse) return { ...pulse };
    // Tool-based events
    const icon = TOOL_ICONS[toolName];
    if (icon) return { ...icon, title: toolName };
    // Generic fallback for unknown pulse event types
    if (eventType && !toolName) {
        const label = eventType.charAt(0).toUpperCase();
        const title = eventType.charAt(0).toUpperCase() + eventType.slice(1);
        return { char: label, cls: 'tool-pulse', title };
    }
    return { char: '.', cls: 'tool-default', title: eventType || 'Event' };
}

function isEventVisible(ev) {
    if (historyFilterHidden.size === 0) return true;
    for (const group of FILTER_GROUPS) {
        if (historyFilterHidden.has(group.key) && group.match(ev)) return false;
    }
    return true;
}

// ── Activity ──────────────────────────────────────────────────────────────

export async function loadHistoryEvents(sessionId) {
    historyFilterHidden = new Set();
    historyEvents = [];
    try {
        const resp = await fetch(`/api/sessions/history/${encodeURIComponent(sessionId)}/events?limit=200`);
        historyEvents = await resp.json();
    } catch (e) {
        historyEvents = [];
    }

    const countEl = document.getElementById('history-activity-count');
    if (countEl) countEl.textContent = historyEvents.length > 0 ? historyEvents.length : '';

    renderHistoryActivityChart();
    renderHistoryEventFilters();
    renderHistoryEventTimeline();
}

function renderHistoryActivityChart() {
    const container = document.getElementById('history-activity-chart');
    if (!container) return;

    if (historyEvents.length === 0) {
        container.innerHTML = '';
        return;
    }

    // Count events by their filter group
    const counts = [];
    const matched = new Set();

    for (const group of FILTER_GROUPS) {
        let groupCount = 0;
        historyEvents.forEach((ev, idx) => {
            if (group.match(ev)) {
                groupCount++;
                matched.add(idx);
            }
        });
        if (groupCount > 0) {
            counts.push({ key: group.key, label: group.title, cls: group.cls, count: groupCount });
        }
    }

    // Catch unmatched events
    const unmatchedCount = historyEvents.length - matched.size;
    if (unmatchedCount > 0) {
        counts.push({ key: 'other', label: 'Other', cls: 'tool-default', count: unmatchedCount });
    }

    if (counts.length === 0) {
        container.innerHTML = '';
        return;
    }

    // Sort by count descending
    counts.sort((a, b) => b.count - a.count);
    const maxCount = counts[0].count;

    const bars = counts.map(item => {
        const pct = Math.max(2, (item.count / maxCount) * 100);
        return `<div class="activity-chart-row">
            <span class="activity-chart-label">${escapeHtml(item.label)}</span>
            <div class="activity-chart-bar-track">
                <div class="activity-chart-bar ${item.cls}" style="width: ${pct}%"></div>
            </div>
            <span class="activity-chart-count">${item.count}</span>
        </div>`;
    }).join('');

    container.innerHTML = bars;
}

function renderHistoryEventFilters() {
    const container = document.getElementById('history-event-filters');
    if (!container) return;

    const allHidden = historyFilterHidden.size === FILTER_GROUPS.length;
    const noneHidden = historyFilterHidden.size === 0;
    const toggleCls = noneHidden ? '' : allHidden ? 'filter-hidden' : 'filter-partial';

    const toggleBtn = `<button class="event-filter-chip filter-toggle ${toggleCls}"
                onclick="toggleAllHistoryEventFilters()"
                title="${noneHidden ? 'Hide all' : 'Show all'}">
                <span class="event-filter-char">*</span>
            </button>`;

    const chips = FILTER_GROUPS.map(group => {
        const count = historyEvents.filter(group.match).length;
        const isHidden = historyFilterHidden.has(group.key);
        const dimClass = isHidden ? 'filter-hidden' : '';
        return `<button class="event-filter-chip ${group.cls} ${dimClass}"
                    onclick="toggleHistoryEventFilter('${group.key}')">
                    <span class="event-filter-char">${group.label}</span>
                </button>`;
    }).join('');

    container.innerHTML = toggleBtn + chips;
}

export function toggleHistoryEventFilter(key) {
    if (historyFilterHidden.has(key)) {
        historyFilterHidden.delete(key);
    } else {
        historyFilterHidden.add(key);
    }
    renderHistoryEventFilters();
    renderHistoryEventTimeline();
}

export function toggleAllHistoryEventFilters() {
    if (historyFilterHidden.size === 0) {
        for (const group of FILTER_GROUPS) historyFilterHidden.add(group.key);
    } else {
        historyFilterHidden.clear();
    }
    renderHistoryEventFilters();
    renderHistoryEventTimeline();
}

function renderHistoryEventTimeline() {
    const container = document.getElementById('history-events-list');
    if (!container) return;

    if (historyEvents.length === 0) {
        container.innerHTML = '<div class="event-empty">No activity recorded</div>';
        return;
    }

    const visible = historyEvents.filter(isEventVisible);
    if (visible.length === 0) {
        container.innerHTML = '<div class="event-empty">All events filtered out</div>';
        return;
    }

    container.innerHTML = visible.map(ev => {
        const icon = getToolIcon(ev.tool_name, ev.event_type);
        const typeCls = ev.event_type ? `event-type-${ev.event_type}` : '';
        return `<div class="event-item ${typeCls}" data-tooltip="${icon.title}: ${escapeAttr(ev.summary)}">
            <span class="event-icon ${icon.cls}">${icon.char}</span>
            <span class="event-body">
                <span class="event-summary">${escapeHtml(ev.summary)}</span>
            </span>
            <span class="event-time">${formatTime(ev.created_at)}</span>
        </div>`;
    }).join('');
}

// ── Tasks ─────────────────────────────────────────────────────────────────

export async function loadHistoryTasks(sessionId) {
    historyTasks = [];
    try {
        const resp = await fetch(`/api/sessions/history/${encodeURIComponent(sessionId)}/tasks`);
        historyTasks = await resp.json();
    } catch (e) {
        historyTasks = [];
    }

    const countEl = document.getElementById('history-tasks-count');
    if (countEl) {
        const doneCount = historyTasks.filter(t => t.completed === 1).length;
        countEl.textContent = historyTasks.length > 0 ? `${doneCount}/${historyTasks.length}` : '';
    }

    renderHistoryTaskList();
}

function renderHistoryTaskList() {
    const list = document.getElementById('history-task-list');
    if (!list) return;

    if (historyTasks.length === 0) {
        list.innerHTML = '<div class="task-empty">No tasks recorded</div>';
        return;
    }

    list.innerHTML = historyTasks.map(t => {
        const statusClass = t.completed === 1 ? 'completed' : t.completed === 2 ? 'in-progress' : '';
        const icon = t.completed === 2
            ? '<span class="task-spinner" title="In progress"></span>'
            : `<input type="checkbox" class="task-checkbox" ${t.completed === 1 ? 'checked' : ''} disabled>`;
        return `
        <div class="task-item ${statusClass}">
            ${icon}
            <span class="task-title">${escapeHtml(t.title)}</span>
        </div>`;
    }).join('');
}

// ── Agent Notes ───────────────────────────────────────────────────────────

export async function loadHistoryAgentNotes(sessionId) {
    historyAgentNotes = [];
    try {
        const resp = await fetch(`/api/sessions/history/${encodeURIComponent(sessionId)}/agent-notes`);
        historyAgentNotes = await resp.json();
    } catch (e) {
        historyAgentNotes = [];
    }

    const countEl = document.getElementById('history-agent-notes-count');
    if (countEl) countEl.textContent = historyAgentNotes.length > 0 ? historyAgentNotes.length : '';

    renderHistoryAgentNotes();
}

function renderHistoryAgentNotes() {
    const container = document.getElementById('history-note-list');
    if (!container) return;

    if (historyAgentNotes.length === 0) {
        container.innerHTML = '<div class="empty-notes">No agent notes recorded</div>';
        return;
    }

    const md = historyAgentNotes.map(n => n.content).join('\n\n');
    if (typeof marked !== 'undefined') {
        container.innerHTML = marked.parse(md);
    } else {
        container.textContent = md;
    }
}
