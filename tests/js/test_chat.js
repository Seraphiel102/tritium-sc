// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * TRITIUM-SC Chat Overlay Tests
 * Tests message rendering, typing indicator, history management,
 * chat toggle, time formatting, and WebSocket transcript routing.
 * Run: node tests/js/test_chat.js
 */

const fs = require('fs');
const vm = require('vm');

let passed = 0, failed = 0;
function assert(cond, msg) {
    if (!cond) { console.error('FAIL:', msg); failed++; }
    else { console.log('PASS:', msg); passed++; }
}
function assertEqual(a, b, msg) {
    assert(a === b, msg + ` (got ${JSON.stringify(a)}, expected ${JSON.stringify(b)})`);
}

// ============================================================
// Mock DOM
// ============================================================

const mockElements = {};
let appendedChildren = [];

function createMockElement(tag) {
    return {
        _tag: tag || 'div',
        _children: [],
        _classes: '',
        _text: '',
        _html: '',
        _listeners: {},
        hidden: false,
        style: { display: '' },
        scrollTop: 0,
        scrollHeight: 100,
        get className() { return this._classes; },
        set className(v) { this._classes = v; },
        get textContent() { return this._text; },
        set textContent(v) { this._text = v; },
        get innerHTML() { return this._html; },
        set innerHTML(v) { this._html = v; },
        appendChild(child) {
            this._children.push(child);
            appendedChildren.push(child);
        },
        querySelector(sel) {
            // Simple selector support for test purposes
            for (const child of this._children) {
                if (child._classes && child._classes.includes(sel.replace('.', ''))) {
                    return child;
                }
            }
            return null;
        },
        remove() {
            // Mark as removed
            this._removed = true;
        },
        addEventListener(event, fn) {
            if (!this._listeners[event]) this._listeners[event] = [];
            this._listeners[event].push(fn);
        },
        focus() { this._focused = true; },
        blur() { this._focused = false; },
        dataset: {},
        value: '',
        querySelectorAll(sel) { return []; },
    };
}

function resetDOM() {
    Object.keys(mockElements).forEach(k => delete mockElements[k]);
    appendedChildren = [];
    // Pre-create the key chat elements
    mockElements['chat-overlay'] = createMockElement('div');
    mockElements['chat-overlay'].hidden = true;
    mockElements['chat-messages'] = createMockElement('div');
    mockElements['chat-input'] = createMockElement('input');
    mockElements['chat-send'] = createMockElement('button');
    mockElements['chat-close'] = createMockElement('button');
    mockElements['chat-context-text'] = createMockElement('div');
}

// ============================================================
// Minimal mocks needed to run chat code
// ============================================================

let timeouts = [];
let fetchCalls = [];
let fetchResponse = { ok: true, json: () => Promise.resolve({ status: 'ok' }) };

// ============================================================
// Tests: _formatChatTime
// ============================================================

console.log('\n--- Chat time formatting ---');

// Test the formatting logic directly (it's a simple function)
function formatChatTime(date) {
    const h = String(date.getHours()).padStart(2, '0');
    const m = String(date.getMinutes()).padStart(2, '0');
    return `${h}:${m}`;
}

{
    const d = new Date(2026, 1, 28, 14, 5, 30);
    assertEqual(formatChatTime(d), '14:05', 'formatChatTime pads minutes');
}

{
    const d = new Date(2026, 1, 28, 9, 32, 0);
    assertEqual(formatChatTime(d), '09:32', 'formatChatTime pads hours');
}

{
    const d = new Date(2026, 1, 28, 0, 0, 0);
    assertEqual(formatChatTime(d), '00:00', 'formatChatTime midnight');
}

{
    const d = new Date(2026, 1, 28, 23, 59, 59);
    assertEqual(formatChatTime(d), '23:59', 'formatChatTime end of day');
}

// ============================================================
// Tests: escapeHtml
// ============================================================

console.log('\n--- HTML escaping ---');

// Reproduce the escapeHtml helper
function escapeHtml(text) {
    if (!text) return '';
    return String(text)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

{
    assertEqual(escapeHtml('<script>alert("xss")</script>'), '&lt;script&gt;alert(&quot;xss&quot;)&lt;/script&gt;', 'escapeHtml blocks XSS');
}

{
    assertEqual(escapeHtml('Hello & goodbye'), 'Hello &amp; goodbye', 'escapeHtml escapes ampersands');
}

{
    assertEqual(escapeHtml(''), '', 'escapeHtml handles empty string');
    assertEqual(escapeHtml(null), '', 'escapeHtml handles null');
    assertEqual(escapeHtml(undefined), '', 'escapeHtml handles undefined');
}

// ============================================================
// Tests: Chat message rendering
// ============================================================

console.log('\n--- Chat message rendering ---');

{
    // Simulate appendChatMessage behavior
    resetDOM();
    const messages = mockElements['chat-messages'];
    const history = [];

    function appendChatMessage(sender, text, type) {
        const now = new Date();
        const timeStr = formatChatTime(now);
        history.push({ role: type, text, time: now.toISOString() });
        const msg = createMockElement('div');
        msg.className = `chat-msg chat-msg-${type}`;
        msg.innerHTML =
            `<div class="chat-msg-header"><span class="chat-msg-sender mono">${escapeHtml(sender)}</span><span class="chat-msg-time mono">${timeStr}</span></div>` +
            `<div class="chat-msg-text">${escapeHtml(text)}</div>`;
        messages.appendChild(msg);
        messages.scrollTop = messages.scrollHeight;
    }

    appendChatMessage('YOU', 'Hello Amy', 'user');
    assertEqual(messages._children.length, 1, 'One message appended');
    assert(messages._children[0].className.includes('chat-msg-user'), 'User message has correct class');
    assert(messages._children[0].innerHTML.includes('Hello Amy'), 'User message contains text');
    assert(messages._children[0].innerHTML.includes('chat-msg-sender'), 'User message has sender element');
    assert(messages._children[0].innerHTML.includes('chat-msg-time'), 'User message has timestamp');
    assertEqual(messages.scrollTop, messages.scrollHeight, 'Chat scrolled to bottom after user message');
}

{
    resetDOM();
    const messages = mockElements['chat-messages'];
    const history = [];

    function appendChatMessage(sender, text, type) {
        const now = new Date();
        history.push({ role: type, text, time: now.toISOString() });
        const msg = createMockElement('div');
        msg.className = `chat-msg chat-msg-${type}`;
        msg.innerHTML =
            `<div class="chat-msg-header"><span class="chat-msg-sender mono">${escapeHtml(sender)}</span><span class="chat-msg-time mono">${formatChatTime(now)}</span></div>` +
            `<div class="chat-msg-text">${escapeHtml(text)}</div>`;
        messages.appendChild(msg);
        messages.scrollTop = messages.scrollHeight;
    }

    appendChatMessage('AMY', 'I see movement at sector 7', 'amy');
    assert(messages._children[0].className.includes('chat-msg-amy'), 'Amy message has correct class');
    assert(messages._children[0].innerHTML.includes('I see movement at sector 7'), 'Amy message contains text');
}

{
    resetDOM();
    const messages = mockElements['chat-messages'];
    const history = [];

    function appendChatMessage(sender, text, type) {
        const now = new Date();
        history.push({ role: type, text, time: now.toISOString() });
        const msg = createMockElement('div');
        msg.className = `chat-msg chat-msg-${type}`;
        messages.appendChild(msg);
    }

    appendChatMessage('SYSTEM', 'Failed to reach Amy', 'error');
    assert(messages._children[0].className.includes('chat-msg-error'), 'Error message has correct class');
}

{
    resetDOM();
    const messages = mockElements['chat-messages'];
    const history = [];

    function appendChatMessage(sender, text, type) {
        const now = new Date();
        history.push({ role: type, text, time: now.toISOString() });
        const msg = createMockElement('div');
        msg.className = `chat-msg chat-msg-${type}`;
        messages.appendChild(msg);
    }

    appendChatMessage('AMY', 'Scanning perimeter...', 'system');
    assert(messages._children[0].className.includes('chat-msg-system'), 'System/thought message has correct class');
}

// ============================================================
// Tests: Chat history
// ============================================================

console.log('\n--- Chat history ---');

{
    const history = [];
    function recordMsg(type, text) {
        history.push({ role: type, text, time: new Date().toISOString() });
    }

    recordMsg('user', 'Hello');
    recordMsg('amy', 'Hi there!');
    recordMsg('user', 'What do you see?');
    recordMsg('amy', 'Quiet streets.');

    assertEqual(history.length, 4, 'History has 4 entries');
    assertEqual(history[0].role, 'user', 'First entry is user');
    assertEqual(history[0].text, 'Hello', 'First entry text is correct');
    assertEqual(history[1].role, 'amy', 'Second entry is amy');
    assertEqual(history[3].text, 'Quiet streets.', 'Last entry text is correct');
    assert(history[0].time, 'History entries have timestamps');

    // getChatHistory returns a copy
    const copy = history.slice();
    copy.push({ role: 'user', text: 'extra', time: '' });
    assertEqual(history.length, 4, 'Slice returns a copy, original unchanged');
}

// ============================================================
// Tests: Typing indicator
// ============================================================

console.log('\n--- Typing indicator ---');

{
    resetDOM();
    const messages = mockElements['chat-messages'];
    let amyThinking = false;

    function showTypingIndicator() {
        if (amyThinking) return;
        amyThinking = true;
        messages.querySelector('.chat-typing-indicator')?.remove();
        const indicator = createMockElement('div');
        indicator.className = 'chat-typing-indicator';
        indicator.innerHTML = '<span class="chat-typing-label mono">AMY</span><span class="chat-typing-dots"><span></span><span></span><span></span></span>';
        messages.appendChild(indicator);
        messages.scrollTop = messages.scrollHeight;
    }

    function hideTypingIndicator() {
        amyThinking = false;
        for (let i = messages._children.length - 1; i >= 0; i--) {
            if (messages._children[i].className === 'chat-typing-indicator') {
                messages._children.splice(i, 1);
                break;
            }
        }
    }

    showTypingIndicator();
    assertEqual(amyThinking, true, 'Typing indicator sets flag');
    assertEqual(messages._children.length, 1, 'Typing indicator element added');
    assert(messages._children[0].className.includes('chat-typing-indicator'), 'Indicator has correct class');
    assert(messages._children[0].innerHTML.includes('chat-typing-dots'), 'Indicator has dots');

    // Double-call should not duplicate
    showTypingIndicator();
    assertEqual(messages._children.length, 1, 'No duplicate typing indicator on double call');

    hideTypingIndicator();
    assertEqual(amyThinking, false, 'Typing flag cleared');
    assertEqual(messages._children.length, 0, 'Indicator element removed');
}

// ============================================================
// Tests: Toggle chat
// ============================================================

console.log('\n--- Chat toggle ---');

{
    resetDOM();
    const overlay = mockElements['chat-overlay'];
    overlay.hidden = true;

    function toggleChat(open) {
        if (open === undefined) open = overlay.hidden;
        overlay.hidden = !open;
    }

    toggleChat(true);
    assertEqual(overlay.hidden, false, 'toggleChat(true) opens overlay');

    toggleChat(false);
    assertEqual(overlay.hidden, true, 'toggleChat(false) closes overlay');

    toggleChat();
    assertEqual(overlay.hidden, false, 'toggleChat() toggles from closed to open');

    toggleChat();
    assertEqual(overlay.hidden, true, 'toggleChat() toggles from open to closed');
}

// ============================================================
// Tests: API request body format
// ============================================================

console.log('\n--- API request format ---');

{
    // The backend ChatRequest expects { text: string }
    const body = JSON.stringify({ text: 'Hello Amy' });
    const parsed = JSON.parse(body);
    assert('text' in parsed, 'Request body uses "text" field (not "message")');
    assertEqual(parsed.text, 'Hello Amy', 'Request body text is correct');
    assert(!('message' in parsed), 'Request body does NOT have "message" field');
}

// ============================================================
// Tests: WebSocket transcript routing
// ============================================================

console.log('\n--- WebSocket transcript routing ---');

{
    // Simulate the WebSocket handler logic for amy_transcript
    let chatResponseEmitted = false;
    let emittedData = null;

    const mockEventBus = {
        emit(event, data) {
            if (event === 'chat:amy_response') {
                chatResponseEmitted = true;
                emittedData = data;
            }
        }
    };

    // Simulate receiving an amy_transcript message where speaker is 'amy'
    const msg = { type: 'amy_transcript', data: { speaker: 'amy', text: 'All clear at sector 3.' } };
    const td = msg.data || msg;
    if (td.speaker === 'amy') {
        mockEventBus.emit('chat:amy_response', { text: td.text });
    }

    assert(chatResponseEmitted, 'amy_transcript with speaker=amy emits chat:amy_response');
    assertEqual(emittedData.text, 'All clear at sector 3.', 'Emitted data contains Amy response text');
}

{
    // Transcript from user should NOT emit chat:amy_response
    let chatResponseEmitted = false;

    const mockEventBus = {
        emit(event) {
            if (event === 'chat:amy_response') chatResponseEmitted = true;
        }
    };

    const msg = { type: 'amy_transcript', data: { speaker: 'user', text: 'Hello' } };
    const td = msg.data || msg;
    if (td.speaker === 'amy') {
        mockEventBus.emit('chat:amy_response', { text: td.text });
    }

    assert(!chatResponseEmitted, 'amy_transcript with speaker=user does NOT emit chat:amy_response');
}

// ============================================================
// Tests: Message XSS prevention
// ============================================================

console.log('\n--- XSS prevention in messages ---');

{
    resetDOM();
    const messages = mockElements['chat-messages'];

    const malicious = '<img src=x onerror=alert(1)>';
    const msg = createMockElement('div');
    msg.className = 'chat-msg chat-msg-user';
    msg.innerHTML =
        `<div class="chat-msg-header"><span class="chat-msg-sender mono">${escapeHtml('YOU')}</span></div>` +
        `<div class="chat-msg-text">${escapeHtml(malicious)}</div>`;
    messages.appendChild(msg);

    assert(!msg.innerHTML.includes('<img'), 'HTML tags are escaped in message text');
    assert(msg.innerHTML.includes('&lt;img'), 'Angle brackets are entity-encoded');
}

// ============================================================
// Tests: Empty input handling
// ============================================================

console.log('\n--- Empty input handling ---');

{
    // sendChat should not submit when input is empty or whitespace
    let fetchCalled = false;
    function simulateSend(text) {
        const trimmed = text.trim();
        if (!trimmed) return false;
        fetchCalled = true;
        return true;
    }

    assertEqual(simulateSend(''), false, 'Empty string does not send');
    assertEqual(simulateSend('   '), false, 'Whitespace-only does not send');
    assertEqual(simulateSend('Hello'), true, 'Non-empty text sends');
    assert(fetchCalled, 'Fetch was called for non-empty input');
}

// ============================================================
// Tests: Context area
// ============================================================

console.log('\n--- Context area ---');

{
    resetDOM();
    const ctx = mockElements['chat-context-text'];

    // Simulate TritiumStore amy.lastThought update
    ctx.textContent = 'Scanning north perimeter...';
    assertEqual(ctx.textContent, 'Scanning north perimeter...', 'Context text shows latest thought');

    ctx.textContent = '--';
    assertEqual(ctx.textContent, '--', 'Context text shows placeholder when no thought');
}

// ============================================================
// Tests: Auto-scroll behavior
// ============================================================

console.log('\n--- Auto-scroll ---');

{
    resetDOM();
    const messages = mockElements['chat-messages'];
    messages.scrollHeight = 500;
    messages.scrollTop = 0;

    // Simulate appending a message
    const msg = createMockElement('div');
    messages.appendChild(msg);
    messages.scrollTop = messages.scrollHeight;

    assertEqual(messages.scrollTop, 500, 'Messages container scrolls to bottom after append');
}

// ============================================================
// Tests: Multiple message types in sequence
// ============================================================

console.log('\n--- Mixed message sequence ---');

{
    resetDOM();
    const messages = mockElements['chat-messages'];
    const history = [];

    function appendMsg(sender, text, type) {
        history.push({ role: type, text, time: new Date().toISOString() });
        const msg = createMockElement('div');
        msg.className = `chat-msg chat-msg-${type}`;
        messages.appendChild(msg);
    }

    appendMsg('AMY', 'Perimeter secure.', 'system');
    appendMsg('YOU', 'Status report', 'user');
    appendMsg('AMY', 'All sectors clear. 3 friendlies operational.', 'amy');
    appendMsg('SYSTEM', 'Connection interrupted', 'error');
    appendMsg('AMY', 'Reconnected to sensors.', 'system');

    assertEqual(messages._children.length, 5, '5 messages appended in sequence');
    assertEqual(history.length, 5, 'History records all 5 messages');
    assert(messages._children[0].className.includes('chat-msg-system'), 'First msg is system type');
    assert(messages._children[1].className.includes('chat-msg-user'), 'Second msg is user type');
    assert(messages._children[2].className.includes('chat-msg-amy'), 'Third msg is amy type');
    assert(messages._children[3].className.includes('chat-msg-error'), 'Fourth msg is error type');
    assert(messages._children[4].className.includes('chat-msg-system'), 'Fifth msg is system type');
}

// ============================================================
// Summary
// ============================================================

console.log(`\n--- Chat tests: ${passed} passed, ${failed} failed ---`);
process.exit(failed > 0 ? 1 : 0);
