/* xterm.js terminal renderer — streams raw ANSI output via WebSocket */

import { state } from './state.js';

let terminal = null;
let fitAddon = null;
let terminalWs = null;

export function createTerminal(containerEl) {
    if (terminal) {
        disposeTerminal();
    }

    if (typeof Terminal === 'undefined') {
        console.warn('xterm.js not loaded, falling back to semantic renderer');
        return null;
    }

    terminal = new Terminal({
        cursorBlink: false,
        cursorStyle: 'block',
        disableStdin: true,
        scrollback: 1000,
        fontSize: 13,
        fontFamily: "'SF Mono', 'Fira Code', 'Cascadia Code', Menlo, monospace",
        theme: {
            background: '#0d1117',
            foreground: '#e6edf3',
            cursor: '#e6edf3',
            selectionBackground: '#264f78',
            black: '#484f58',
            red: '#f85149',
            green: '#3fb950',
            yellow: '#d29922',
            blue: '#58a6ff',
            magenta: '#bc8cff',
            cyan: '#39d2c0',
            white: '#e6edf3',
            brightBlack: '#6e7681',
            brightRed: '#ffa198',
            brightGreen: '#56d364',
            brightYellow: '#e3b341',
            brightBlue: '#79c0ff',
            brightMagenta: '#d2a8ff',
            brightCyan: '#56d4dd',
            brightWhite: '#f0f6fc',
        },
    });

    fitAddon = new FitAddon.FitAddon();
    terminal.loadAddon(fitAddon);

    if (typeof WebLinksAddon !== 'undefined') {
        const webLinksAddon = new WebLinksAddon.WebLinksAddon();
        terminal.loadAddon(webLinksAddon);
    }

    terminal.open(containerEl);
    fitAddon.fit();

    return terminal;
}

export function connectTerminalWs(name, agentType, sessionId) {
    disconnectTerminalWs();

    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    const params = new URLSearchParams();
    if (agentType) params.set("agent_type", agentType);
    if (sessionId) params.set("session_id", sessionId);
    const qs = params.toString() ? `?${params}` : "";

    terminalWs = new WebSocket(
        `${proto}//${location.host}/ws/terminal/${encodeURIComponent(name)}${qs}`
    );

    terminalWs.onmessage = (event) => {
        const data = JSON.parse(event.data);
        if (data.type === "terminal_update" && terminal) {
            terminal.reset();
            // tmux outputs \n but xterm.js needs \r\n for proper line breaks
            terminal.write(data.content.replace(/\n/g, '\r\n'));
            if (state.autoScroll) {
                terminal.scrollToBottom();
            }
        }
    };

    terminalWs.onclose = () => {
        if (state.currentSession && state.currentSession.type === "live") {
            setTimeout(() => {
                if (state.currentSession && state.currentSession.name === name) {
                    connectTerminalWs(name, agentType, sessionId);
                }
            }, 3000);
        }
    };
}

export function disconnectTerminalWs() {
    if (terminalWs) {
        terminalWs.close();
        terminalWs = null;
    }
}

export function disposeTerminal() {
    disconnectTerminalWs();
    if (terminal) {
        terminal.dispose();
        terminal = null;
        fitAddon = null;
    }
}

export function fitTerminal() {
    if (fitAddon) {
        fitAddon.fit();
    }
}

export function getTerminal() {
    return terminal;
}
