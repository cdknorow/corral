/* Directory browser for session launch modal */

import { escapeHtml, escapeAttr } from './utils.js';

let browserCurrentPath = "~";

export function toggleBrowser() {
    const browser = document.getElementById("dir-browser");
    const isVisible = browser.style.display !== "none";
    browser.style.display = isVisible ? "none" : "";
    if (!isVisible) {
        const inputPath = document.getElementById("launch-dir").value.trim();
        browserCurrentPath = inputPath || "~";
        loadBrowserEntries(browserCurrentPath);
    }
}

async function loadBrowserEntries(path) {
    const list = document.getElementById("browser-list");
    const pathDisplay = document.getElementById("browser-current-path");
    list.innerHTML = '<li class="empty-state">Loading...</li>';

    try {
        const resp = await fetch(`/api/filesystem/list?path=${encodeURIComponent(path)}`);
        const data = await resp.json();

        if (data.error) {
            list.innerHTML = `<li class="empty-state">${escapeHtml(data.error)}</li>`;
            return;
        }

        browserCurrentPath = data.path;
        pathDisplay.textContent = data.path;
        document.getElementById("launch-dir").value = data.path;

        if (!data.entries.length) {
            list.innerHTML = '<li class="empty-state">No subdirectories</li>';
            return;
        }

        list.innerHTML = data.entries.map(name =>
            `<li onclick="browserNavigateTo('${escapeAttr(name)}')" title="${escapeHtml(name)}">
                <span class="dir-icon">&#128193;</span>
                <span class="dir-name">${escapeHtml(name)}</span>
            </li>`
        ).join("");
    } catch (e) {
        list.innerHTML = '<li class="empty-state">Failed to load</li>';
        console.error("Browser load error:", e);
    }
}

export function browserNavigateTo(name) {
    const newPath = browserCurrentPath + "/" + name;
    loadBrowserEntries(newPath);
}

export function browserNavigateUp() {
    const parts = browserCurrentPath.split("/");
    if (parts.length > 1) {
        parts.pop();
        const parent = parts.join("/") || "/";
        loadBrowserEntries(parent);
    }
}
