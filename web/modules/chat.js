import { escapeHtml, renderMarkdown } from './utils.js';

export function initChat({ ws, state, updateUnreadBadge }) {
    const container = document.getElementById('content');

    const page = document.createElement('div');
    page.id = 'page-chat';
    page.className = 'page active';
    page.innerHTML = `
        <div class="page-header">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" stroke-width="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
            <h2>Chat</h2>
            <div class="spacer"></div>
            <span id="chat-status" class="status-badge offline">Connecting...</span>
        </div>
        <div id="chat-messages"></div>
        <div id="chat-input-area">
            <textarea id="chat-input" placeholder="Message Ouroboros..." rows="1"></textarea>
            <button class="icon-btn" id="chat-send">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>
            </button>
        </div>
    `;
    container.appendChild(page);

    const messagesDiv = document.getElementById('chat-messages');
    const input = document.getElementById('chat-input');
    const sendBtn = document.getElementById('chat-send');

    const _chatHistory = [];
    const sentInputHistory = [];
    const seenMessageKeys = new Set();
    const messageKeyOrder = [];
    const localUserBubbles = new Map();
    let historyLoaded = false;
    let historySyncPromise = null;
    let inputHistoryIndex = -1;
    let inputDraftBeforeHistory = '';
    const clientSessionId = getOrCreateClientSessionId();

    function getOrCreateClientSessionId() {
        const storageKey = 'ouro_chat_client_session_id';
        try {
            const existing = sessionStorage.getItem(storageKey);
            if (existing) return existing;
            const generated = (globalThis.crypto?.randomUUID?.() || `session-${Date.now()}-${Math.random().toString(16).slice(2)}`).replace(/[^a-zA-Z0-9-]/g, '');
            sessionStorage.setItem(storageKey, generated);
            return generated;
        } catch {
            return `session-${Date.now()}-${Math.random().toString(16).slice(2)}`;
        }
    }

    function shortSessionId(sessionId) {
        const normalized = String(sessionId || '').trim();
        return normalized ? normalized.slice(0, 8) : 'unknown';
    }

    function buildUserSenderLabel(sessionId, isLocalSender) {
        const prefix = isLocalSender ? 'You' : 'Another User';
        return `${prefix} (${shortSessionId(sessionId)})`;
    }

    function buildMessageKey(role, text, timestamp, isProgress = false, systemType = '') {
        if (!timestamp) return '';
        return `${role}|${isProgress ? '1' : '0'}|${systemType}|${timestamp}|${text}`;
    }

    function rememberMessageKey(key) {
        if (!key || seenMessageKeys.has(key)) return;
        seenMessageKeys.add(key);
        messageKeyOrder.push(key);
        if (messageKeyOrder.length > 2000) {
            const oldest = messageKeyOrder.shift();
            if (oldest) seenMessageKeys.delete(oldest);
        }
    }

    function formatMsgTime(isoStr) {
        if (!isoStr) return null;
        try {
            const d = new Date(isoStr);
            if (isNaN(d)) return null;
            const now = new Date();
            const pad = n => String(n).padStart(2, '0');
            const hhmm = `${pad(d.getHours())}:${pad(d.getMinutes())}`;
            const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
            const todayStr = now.toDateString();
            const yesterday = new Date(now); yesterday.setDate(now.getDate() - 1);
            let short;
            if (d.toDateString() === todayStr) {
                short = hhmm;
            } else if (d.toDateString() === yesterday.toDateString()) {
                short = `Yesterday, ${hhmm}`;
            } else {
                short = `${months[d.getMonth()]} ${d.getDate()}, ${hhmm}`;
            }
            const full = `${months[d.getMonth()]} ${d.getDate()}, ${d.getFullYear()} at ${hhmm}`;
            return { short, full };
        } catch { return null; }
    }

    const pendingUserBubbles = new Map();
    let welcomeShown = false;

    function getSenderLabel(role, isProgress = false, systemType = '', senderLabel = '') {
        if (senderLabel) return senderLabel;
        if (role === 'user') return 'You';
        if (role === 'system') {
            return systemType === 'task_summary' ? '📋 Task Summary' : '📋 System';
        }
        if (isProgress) return '💬 Thought';
        return 'Ouroboros';
    }

    function addMessage(text, role, markdown = false, timestamp = null, isProgress = false, opts = {}) {
        const pending = !!opts.pending;
        const ephemeral = !!opts.ephemeral;
        const clientMessageId = opts.clientMessageId || '';
        const systemType = opts.systemType || '';
        const senderLabel = opts.senderLabel || '';
        const ts = timestamp || new Date().toISOString();
        const messageKey = role === 'user' ? '' : buildMessageKey(role, text, ts, isProgress, systemType);
        if (messageKey && seenMessageKeys.has(messageKey)) return null;
        if (!isProgress && !ephemeral) {
            _chatHistory.push({ text, role, ts, markdown: !!markdown, systemType });
        }
        const bubble = document.createElement('div');
        bubble.className = `chat-bubble ${role}` + (isProgress ? ' progress' : '');
        if (pending) bubble.classList.add('pending');
        if (ephemeral) bubble.dataset.ephemeral = '1';
        if (clientMessageId) bubble.dataset.clientMessageId = clientMessageId;
        if (systemType) bubble.dataset.systemType = systemType;
        const sender = getSenderLabel(role, isProgress, systemType, senderLabel);
        const rendered = role === 'user' ? escapeHtml(text) : renderMarkdown(text);
        const timeFmt = formatMsgTime(ts);
        const timeHtml = timeFmt
            ? `<div class="msg-time" title="${timeFmt.full}">${timeFmt.short}</div>`
            : '';
        const pendingHtml = pending ? `<div class="msg-pending">Queued until reconnect</div>` : '';
        bubble.innerHTML = `
            <div class="sender">${sender}</div>
            <div class="message">${rendered}</div>
            ${pendingHtml}
            ${timeHtml}
        `;
        const typing = document.getElementById('typing-indicator');
        if (typing && typing.parentNode === messagesDiv) {
            messagesDiv.insertBefore(bubble, typing);
        } else {
            messagesDiv.appendChild(bubble);
        }
        messagesDiv.scrollTop = messagesDiv.scrollHeight;
        if (!ephemeral) {
            try { sessionStorage.setItem('ouro_chat', JSON.stringify(_chatHistory.slice(-200))); } catch {}
        }
        rememberMessageKey(messageKey);
        if (pending && clientMessageId) pendingUserBubbles.set(clientMessageId, bubble);
        if (role === 'user' && clientMessageId) localUserBubbles.set(clientMessageId, bubble);
        return bubble;
    }

    function reconcileLocalUserMessage(msg) {
        const clientMessageId = msg?.client_message_id || '';
        if (!clientMessageId) return false;
        const bubble = localUserBubbles.get(clientMessageId);
        if (!bubble) return false;

        bubble.classList.remove('pending');
        bubble.querySelector('.msg-pending')?.remove();

        const ts = msg.ts || new Date().toISOString();
        const timeFmt = formatMsgTime(ts);
        let timeEl = bubble.querySelector('.msg-time');
        if (!timeFmt) return true;

        if (!timeEl) {
            timeEl = document.createElement('div');
            timeEl.className = 'msg-time';
            bubble.appendChild(timeEl);
        }
        timeEl.textContent = timeFmt.short;
        timeEl.title = timeFmt.full;
        return true;
    }

    function ensureWelcomeMessage() {
        if (welcomeShown) return;
        const hasRealBubbles = Array.from(messagesDiv.querySelectorAll('.chat-bubble')).some(
            bubble => !bubble.classList.contains('typing-bubble')
        );
        if (hasRealBubbles) return;
        welcomeShown = true;
        addMessage('Ouroboros has awakened', 'assistant', false, null, false, { ephemeral: true });
    }

    async function syncHistory({ includeUser = false } = {}) {
        if (historySyncPromise) return historySyncPromise;
        historySyncPromise = (async () => {
            try {
                const resp = await fetch('/api/chat/history?limit=1000', { cache: 'no-store' });
                if (!resp.ok) return false;
                const data = await resp.json();
                const messages = Array.isArray(data.messages) ? data.messages : [];
                for (const msg of messages) {
                    if (!includeUser && msg.role === 'user') continue;
                    addMessage(msg.text, msg.role, !!msg.markdown, msg.ts || null, !!msg.is_progress, {
                        systemType: msg.system_type || '',
                    });
                }
                historyLoaded = true;
                return messages.length > 0;
            } catch (err) {
                console.error('Failed to load chat history:', err);
                return false;
            } finally {
                historySyncPromise = null;
            }
        })();
        return historySyncPromise;
    }

    // Restore chat history from server (persists across app restarts)
    (async () => {
        if (await syncHistory({ includeUser: true })) return;
        // Fallback: sessionStorage (survives page reload but not app restart)
        try {
            const saved = JSON.parse(sessionStorage.getItem('ouro_chat') || '[]');
            for (const msg of saved) {
                addMessage(msg.text, msg.role, !!msg.markdown, msg.ts || null, false, {
                    systemType: msg.systemType || '',
                });
            }
        } catch {}
        historyLoaded = true;
        ensureWelcomeMessage();
    })();

    function sendMessage() {
        const text = input.value.trim();
        if (!text) return;
        sentInputHistory.push(text);
        if (sentInputHistory.length > 100) sentInputHistory.shift();
        inputHistoryIndex = -1;
        inputDraftBeforeHistory = '';
        input.value = '';
        input.style.height = 'auto';
        const result = ws.send({ type: 'chat', content: text, sender_session_id: clientSessionId });
        addMessage(text, 'user', false, null, false, {
            pending: result?.status === 'queued',
            clientMessageId: result?.clientMessageId || '',
            senderLabel: buildUserSenderLabel(clientSessionId, true),
        });
    }

    sendBtn.addEventListener('click', sendMessage);
    input.addEventListener('keydown', (e) => {
        if (e.key === 'ArrowUp' && !e.shiftKey) {
            const isEmpty = !input.value.trim();
            const isNavigatingHistory = inputHistoryIndex >= 0;
            if ((isEmpty || isNavigatingHistory) && sentInputHistory.length) {
                e.preventDefault();
                if (inputHistoryIndex < 0) {
                    inputDraftBeforeHistory = input.value;
                    inputHistoryIndex = sentInputHistory.length - 1;
                } else if (inputHistoryIndex > 0) {
                    inputHistoryIndex -= 1;
                }
                input.value = sentInputHistory[inputHistoryIndex] || '';
                input.style.height = 'auto';
                input.style.height = Math.min(input.scrollHeight, 120) + 'px';
                input.setSelectionRange(input.value.length, input.value.length);
                return;
            }
        }
        if (e.key === 'ArrowDown' && !e.shiftKey && inputHistoryIndex >= 0) {
            e.preventDefault();
            if (inputHistoryIndex < sentInputHistory.length - 1) {
                inputHistoryIndex += 1;
                input.value = sentInputHistory[inputHistoryIndex] || '';
            } else {
                inputHistoryIndex = -1;
                input.value = inputDraftBeforeHistory;
                inputDraftBeforeHistory = '';
            }
            input.style.height = 'auto';
            input.style.height = Math.min(input.scrollHeight, 120) + 'px';
            input.setSelectionRange(input.value.length, input.value.length);
            return;
        }
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });
    input.addEventListener('input', () => {
        if (inputHistoryIndex === -1) {
            inputDraftBeforeHistory = input.value;
        }
        input.style.height = 'auto';
        input.style.height = Math.min(input.scrollHeight, 120) + 'px';
    });

    // Typing indicator element (persistent, shown/hidden as needed)
    const typingEl = document.createElement('div');
    typingEl.id = 'typing-indicator';
    typingEl.className = 'chat-bubble assistant typing-bubble';
    typingEl.style.display = 'none';
    typingEl.innerHTML = `<div class="typing-dots"><span></span><span></span><span></span></div>`;
    messagesDiv.appendChild(typingEl);

    function showTyping() {
        typingEl.style.display = '';
        messagesDiv.scrollTop = messagesDiv.scrollHeight;
        const badge = document.getElementById('chat-status');
        if (badge) {
            badge.className = 'status-badge thinking';
            badge.textContent = 'Thinking...';
        }
    }
    function hideTyping() {
        typingEl.style.display = 'none';
        const badge = document.getElementById('chat-status');
        if (badge && badge.textContent === 'Thinking...') {
            badge.className = 'status-badge online';
            badge.textContent = 'Online';
        }
    }

    ws.on('typing', () => { showTyping(); });

    ws.on('chat', (msg) => {
        if (msg.role === 'user') {
            const reconciled = reconcileLocalUserMessage(msg);
            if (!reconciled) {
                const senderSessionId = String(msg.sender_session_id || '').trim();
                const isLocalSender = senderSessionId && senderSessionId === clientSessionId;
                addMessage(msg.content, 'user', false, msg.ts || null, false, {
                    clientMessageId: msg.client_message_id || '',
                    senderLabel: buildUserSenderLabel(senderSessionId, isLocalSender),
                });
            }
            if (state.activePage !== 'chat') {
                state.unreadCount++;
                updateUnreadBadge();
            }
            return;
        }
        if (msg.role === 'assistant' || msg.role === 'system') {
            hideTyping();
            addMessage(msg.content, msg.role, msg.markdown, msg.ts || null, !!msg.is_progress, {
                systemType: msg.system_type || '',
            });
            if (state.activePage !== 'chat') {
                state.unreadCount++;
                updateUnreadBadge();
            }
        }
    });

    ws.on('outbound_sent', (evt) => {
        const bubble = pendingUserBubbles.get(evt?.clientMessageId || '');
        if (!bubble) return;
        bubble.classList.remove('pending');
        bubble.querySelector('.msg-pending')?.remove();
        pendingUserBubbles.delete(evt.clientMessageId);
    });

    ws.on('photo', (msg) => {
        hideTyping();
        const bubble = document.createElement('div');
        bubble.className = 'chat-bubble assistant';
        const timeFmt = formatMsgTime(msg.ts || new Date().toISOString());
        const timeHtml = timeFmt
            ? `<div class="msg-time" title="${timeFmt.full}">${timeFmt.short}</div>`
            : '';
        const captionHtml = msg.caption ? `<div class="message">${escapeHtml(msg.caption)}</div>` : '';
        bubble.innerHTML = `
            <div class="sender">Ouroboros</div>
            ${captionHtml}
            <div class="message"><img src="data:${msg.mime || 'image/png'};base64,${msg.image_base64}" style="max-width:100%;border-radius:8px;cursor:pointer" onclick="window.open(this.src,'_blank')" /></div>
            ${timeHtml}
        `;
        const typing = document.getElementById('typing-indicator');
        const messagesDiv = document.getElementById('chat-messages');
        if (typing && typing.parentNode === messagesDiv) {
            messagesDiv.insertBefore(bubble, typing);
        } else {
            messagesDiv.appendChild(bubble);
        }
        messagesDiv.scrollTop = messagesDiv.scrollHeight;
        if (state.activePage !== 'chat') {
            state.unreadCount++;
            updateUnreadBadge();
        }
    });

    ws.on('open', () => {
        document.getElementById('chat-status').className = 'status-badge online';
        document.getElementById('chat-status').textContent = 'Online';
        syncHistory({ includeUser: !historyLoaded })
            .then((hasMessages) => {
                if (!hasMessages) ensureWelcomeMessage();
            })
            .catch(() => {});
    });
    ws.on('close', () => {
        hideTyping();
        document.getElementById('chat-status').className = 'status-badge offline';
        document.getElementById('chat-status').textContent = 'Reconnecting...';
    });

}
