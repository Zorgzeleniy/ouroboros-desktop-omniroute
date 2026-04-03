/**
 * WebSocket Manager module.
 *
 * Connection is deferred: call ws.connect() AFTER all modules
 * have registered their event listeners to avoid race conditions.
 */

export class WS {
    constructor(url) {
        this.url = url;
        this.ws = null;
        this.listeners = {};
        this.reconnectDelay = 1000;
        this.maxDelay = 10000;
        this._wasConnected = false;
        this._lastSha = null;
        this._lastMessageAt = 0;
        this._reconnectTimer = null;
        this._reloadFallbackTimer = null;
        this._watchdogTimer = null;
        this._pendingMessages = [];
        this._nextClientMessageId = 1;
        // Do NOT connect here — wait for all modules to register listeners first
    }

    _getUrl() {
        return typeof this.url === 'function' ? this.url() : this.url;
    }

    _clearReconnectTimer() {
        if (this._reconnectTimer) {
            clearTimeout(this._reconnectTimer);
            this._reconnectTimer = null;
        }
    }

    _clearReloadFallbackTimer() {
        if (this._reloadFallbackTimer) {
            clearTimeout(this._reloadFallbackTimer);
            this._reloadFallbackTimer = null;
        }
    }

    _clearWatchdogTimer() {
        if (this._watchdogTimer) {
            clearInterval(this._watchdogTimer);
            this._watchdogTimer = null;
        }
    }

    _startWatchdog(socket) {
        this._clearWatchdogTimer();
        this._watchdogTimer = setInterval(() => {
            if (this.ws !== socket || socket.readyState !== WebSocket.OPEN) return;
            if (Date.now() - this._lastMessageAt < 45000) return;
            console.warn('WebSocket watchdog forcing reconnect after stale inbound stream');
            try { socket.close(); } catch {}
        }, 10000);
    }

    _scheduleReconnect() {
        if (this._reconnectTimer) return;
        document.getElementById('reconnect-overlay')?.classList.add('visible');
        if (!this._reloadFallbackTimer) {
            // Safety net for stuck embedded-webview reconnect states.
            this._reloadFallbackTimer = setTimeout(() => location.reload(), 15000);
        }
        const delay = this.reconnectDelay;
        this._reconnectTimer = setTimeout(() => {
            this._reconnectTimer = null;
            this.connect();
        }, delay);
        this.reconnectDelay = Math.min(Math.round(this.reconnectDelay * 1.5), this.maxDelay);
    }

    _refreshStateAfterOpen(previouslyConnected) {
        fetch('/api/state', { cache: 'no-store' }).then(r => r.json()).then(d => {
            if (previouslyConnected && this._lastSha && d.sha && d.sha !== this._lastSha) {
                location.reload();
                return;
            }
            this._lastSha = d.sha || this._lastSha;
        }).catch(() => {
            // Keep the socket usable even if the HTTP state probe fails once.
        });
    }

    _flushPendingMessages() {
        if (!this.ws || this.ws.readyState !== WebSocket.OPEN || this._pendingMessages.length === 0) {
            return;
        }
        const queued = [...this._pendingMessages];
        this._pendingMessages = [];
        for (const msg of queued) {
            try {
                this.ws.send(JSON.stringify(msg));
                this.emit('outbound_sent', {
                    clientMessageId: msg.client_message_id || '',
                    queued: true,
                    type: msg.type || '',
                });
            } catch {
                this._pendingMessages.unshift(msg);
                this._scheduleReconnect();
                break;
            }
        }
    }

    connect() {
        if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) {
            return;
        }
        const socket = new WebSocket(this._getUrl());
        this.ws = socket;
        const previouslyConnected = this._wasConnected;
        let disconnected = false;

        const handleDisconnect = () => {
            if (disconnected) return;
            disconnected = true;
            if (this.ws === socket) this.ws = null;
            this._clearWatchdogTimer();
            this.emit('close');
            this._scheduleReconnect();
        };

        socket.onopen = () => {
            if (this.ws !== socket) return;
            this._wasConnected = true;
            this._lastMessageAt = Date.now();
            this._clearReconnectTimer();
            this._clearReloadFallbackTimer();
            this.reconnectDelay = 1000;
            this._startWatchdog(socket);
            this.emit('open');
            document.getElementById('reconnect-overlay')?.classList.remove('visible');
            this._refreshStateAfterOpen(previouslyConnected);
            this._flushPendingMessages();
        };

        socket.onerror = () => {
            handleDisconnect();
            try { socket.close(); } catch {}
        };

        socket.onclose = () => {
            handleDisconnect();
        };

        socket.onmessage = (e) => {
            this._lastMessageAt = Date.now();
            try {
                const msg = JSON.parse(e.data);
                this.emit('message', msg);
                if (msg.type) this.emit(msg.type, msg);
            } catch (err) {
                console.error('WebSocket message handling failed:', err);
            }
        };
    }

    send(msg) {
        const payload = { ...msg };
        if (!payload.client_message_id && payload.type === 'chat') {
            payload.client_message_id = `msg-${Date.now()}-${this._nextClientMessageId++}`;
        }
        if (this.ws?.readyState === WebSocket.OPEN) {
            try {
                this.ws.send(JSON.stringify(payload));
                this.emit('outbound_sent', {
                    clientMessageId: payload.client_message_id || '',
                    queued: false,
                    type: payload.type || '',
                });
                return { status: 'sent', clientMessageId: payload.client_message_id || '' };
            } catch {}
        }
        if (this._pendingMessages.length >= 100) this._pendingMessages.shift();
        this._pendingMessages.push(payload);
        this.emit('outbound_queued', {
            clientMessageId: payload.client_message_id || '',
            type: payload.type || '',
        });
        this._scheduleReconnect();
        this.connect();
        return { status: 'queued', clientMessageId: payload.client_message_id || '' };
    }

    on(event, fn) {
        (this.listeners[event] ||= []).push(fn);
    }

    emit(event, data) {
        (this.listeners[event] || []).forEach(fn => fn(data));
    }
}

export function createWS() {
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    return new WS(() => `${proto}//${location.host}/ws`);
}
