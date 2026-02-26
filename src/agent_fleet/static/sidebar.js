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
    const taskBar = document.getElementById("agentic-state");
    const liveBody = document.querySelector(".live-body");

    if (!handle || !taskBar || !liveBody) return;

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
        const rect = liveBody.getBoundingClientRect();
        const newWidth = rect.right - e.clientX;
        const clamped = Math.min(Math.max(newWidth, 180), 480);
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
    const column = document.querySelector(".live-left-column");

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
        const container = column || document.body;
        const rect = container.getBoundingClientRect();
        const newHeight = rect.bottom - e.clientY;
        const clamped = Math.min(Math.max(newHeight, 80), rect.height * 0.6);
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
