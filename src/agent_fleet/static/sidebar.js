/* Sidebar drag-to-resize functionality */

export function initSidebarResize() {
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

/* Task bar drag-to-resize functionality */

export function initTaskBarResize() {
    const handle = document.getElementById("task-bar-resize-handle");
    const taskBar = document.getElementById("task-bar");
    const outputArea = document.querySelector(".output-area");

    if (!handle || !taskBar || !outputArea) return;

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
        const rect = outputArea.getBoundingClientRect();
        const newWidth = rect.right - e.clientX;
        const clamped = Math.min(Math.max(newWidth, 180), rect.width * 0.5);
        taskBar.style.width = clamped + "px";
    });

    document.addEventListener("mouseup", () => {
        if (!dragging) return;
        dragging = false;
        handle.classList.remove("dragging");
        document.body.style.cursor = "";
        document.body.style.userSelect = "";
    });
}

/* Command pane drag-to-resize functionality */

export function initCommandPaneResize() {
    const handle = document.getElementById("command-pane-resize-handle");
    const pane = document.getElementById("command-pane");

    let dragging = false;

    handle.addEventListener("mousedown", (e) => {
        e.preventDefault();
        dragging = true;
        handle.classList.add("dragging");
        document.body.style.cursor = "row-resize";
        document.body.style.userSelect = "none";
    });

    document.addEventListener("mousemove", (e) => {
        if (!dragging) return;
        const viewportHeight = window.innerHeight;
        const newHeight = viewportHeight - e.clientY;
        const clamped = Math.min(Math.max(newHeight, 80), viewportHeight * 0.6);
        pane.style.height = clamped + "px";
    });

    document.addEventListener("mouseup", () => {
        if (!dragging) return;
        dragging = false;
        handle.classList.remove("dragging");
        document.body.style.cursor = "";
        document.body.style.userSelect = "";
    });
}
