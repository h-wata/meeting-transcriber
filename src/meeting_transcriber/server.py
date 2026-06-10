"""FastAPIベースのWeb UIサーバー."""

from __future__ import annotations

import asyncio
import base64
import logging
import re
import secrets
import signal
import threading
import uuid
import webbrowser
from datetime import datetime
from typing import TYPE_CHECKING

import uvicorn
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel

if TYPE_CHECKING:
    from meeting_transcriber.audio import AudioRecorder
    from meeting_transcriber.config import Config
    from meeting_transcriber.minutes import MinutesUpdater
    from meeting_transcriber.transcriber import Transcriber

# 保存時のファイル名サニタイズ用: 英数 / 日本語 / ハイフン / アンダースコア / ドット / 空白のみ許可
_SAFE_FILENAME_RE = re.compile(r'^[\w\-. ぀-ヿ㐀-鿿]{1,128}$')

INDEX_HTML = """<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<title>Meeting Transcriber</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
html, body { height: 100%; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Hiragino Sans", "Yu Gothic", sans-serif; background: #2a2a3c; color: #e0e6f3; }
#app { display: grid; grid-template-rows: auto 1fr auto; height: 100vh; }
header { padding: 14px 24px; background: linear-gradient(to right, #1a1a2e, #25253a); border-bottom: 2px solid #45475a; display: flex; justify-content: space-between; align-items: center; gap: 16px; }
header h1 { font-size: 22px; font-weight: 700; color: #89b4fa; letter-spacing: 0.5px; display: flex; align-items: center; }
#status { font-size: 13px; color: #cdd6f4; font-weight: 500; }
#controls { display: flex; gap: 6px; }
button { background: #313244; color: #cdd6f4; border: none; padding: 5px 12px; border-radius: 4px; cursor: pointer; font-size: 12px; }
button:hover { background: #45475a; }
button.primary { background: #89b4fa; color: #1e1e2e; }
button.primary:hover { background: #74c7ec; }
button.danger { background: #f38ba8; color: #1e1e2e; }
button:disabled { opacity: 0.5; cursor: not-allowed; }

main { display: grid; grid-template-columns: 1fr 1.6fr 1.1fr; gap: 10px; padding: 10px; overflow: hidden; }
.panel { background: #1e1e30; border: 1px solid #45475a; border-radius: 8px; display: flex; flex-direction: column; overflow: hidden; box-shadow: 0 2px 8px rgba(0,0,0,0.2); }
.panel-header { padding: 8px 14px; background: #15151f; border-bottom: 1px solid #45475a; font-size: 13px; font-weight: 600; color: #94e2d5; display: flex; justify-content: space-between; align-items: center; }
.panel-body { flex: 1; overflow-y: auto; padding: 12px; }

#left { display: grid; grid-template-rows: 1fr auto; gap: 8px; overflow: hidden; min-height: 0; }
#transcript-panel .panel-body { font-family: "JetBrains Mono", "Consolas", monospace; font-size: 13px; line-height: 1.6; }
.transcript-entry { padding: 2px 0; border-bottom: 1px solid #313244; }
.transcript-entry .ts { color: #6c7086; margin-right: 8px; }

#log-panel { max-height: 180px; }
#log-panel .panel-body { font-family: "JetBrains Mono", "Consolas", monospace; font-size: 11px; line-height: 1.5; }
.log-entry { padding: 1px 0; }
.log-entry .ts { color: #6c7086; margin-right: 6px; }
.log-entry.error { color: #f38ba8; }
.log-entry.success { color: #a6e3a1; }
.log-entry.warning { color: #f9e2af; }
.log-entry.info { color: #89dceb; }

#minutes-panel .panel-body { font-size: 14px; line-height: 1.7; }
#minutes-content h1, #minutes-content h2, #minutes-content h3 { margin-top: 1em; margin-bottom: 0.5em; color: #f5c2e7; }
#minutes-content h1 { font-size: 22px; border-bottom: 1px solid #313244; padding-bottom: 4px; }
#minutes-content h2 { font-size: 18px; color: #89b4fa; }
#minutes-content h3 { font-size: 15px; color: #94e2d5; }
#minutes-content ul, #minutes-content ol { margin-left: 24px; margin-bottom: 0.6em; }
#minutes-content li { margin-bottom: 0.2em; }
#minutes-content p { margin-bottom: 0.6em; }
#minutes-content code { background: #313244; padding: 1px 4px; border-radius: 3px; font-size: 0.9em; }
#minutes-content blockquote { border-left: 3px solid #89b4fa; padding-left: 10px; margin: 0.5em 0; color: #a6adc8; }
#minutes-content hr { border: none; border-top: 1px solid #313244; margin: 1em 0; }

footer { padding: 8px 12px; background: #181825; border-top: 1px solid #313244; display: flex; gap: 8px; }
#command-input { flex: 1; background: #313244; color: #cdd6f4; border: 1px solid #45475a; padding: 8px 12px; border-radius: 4px; font-size: 13px; }
#command-input:focus { outline: none; border-color: #89b4fa; }

#chat-panel { display: flex; flex-direction: column; }
#chat-body { display: flex; flex-direction: column; gap: 8px; }
.chat-entry { padding: 8px 10px; border-radius: 6px; font-size: 13px; line-height: 1.5; max-width: 95%; word-wrap: break-word; }
.chat-entry.user { background: #313244; color: #cdd6f4; align-self: flex-end; }
.chat-entry.assistant { background: #1e2030; border-left: 3px solid #89b4fa; color: #cdd6f4; align-self: flex-start; }
.chat-entry.error { background: #2d1b2a; border-left: 3px solid #f38ba8; color: #f38ba8; }
.chat-entry .role { font-size: 10px; color: #6c7086; margin-bottom: 2px; text-transform: uppercase; letter-spacing: 0.5px; }
.chat-entry .body { white-space: pre-wrap; }
#chat-input-row { padding: 6px 8px; border-top: 1px solid #313244; display: flex; gap: 6px; background: #11111b; }
#chat-input { flex: 1; background: #313244; color: #cdd6f4; border: 1px solid #45475a; padding: 6px 10px; border-radius: 4px; font-size: 13px; }
#chat-input:focus { outline: none; border-color: #89b4fa; }
#chat-typing { color: #6c7086; font-size: 11px; font-style: italic; padding: 4px 10px; }

.empty { color: #6c7086; font-style: italic; text-align: center; padding: 30px 20px; }

#shutdown-overlay { position: fixed; inset: 0; background: rgba(20,20,30,0.92); display: flex; align-items: center; justify-content: center; z-index: 9999; backdrop-filter: blur(4px); }
.shutdown-modal { background: #1e1e30; border: 1px solid #45475a; border-radius: 12px; padding: 32px 40px; max-width: 600px; box-shadow: 0 8px 32px rgba(0,0,0,0.4); text-align: center; color: #e0e6f3; }
.shutdown-icon { font-size: 48px; color: #a6e3a1; margin-bottom: 8px; }
.shutdown-modal h2 { font-size: 22px; margin-bottom: 12px; color: #cdd6f4; font-weight: 700; }
.shutdown-stat { font-size: 13px; color: #94e2d5; margin-bottom: 16px; }
.shutdown-path-label { font-size: 11px; color: #6c7086; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 6px; }
.shutdown-path { background: #11111b; border: 1px solid #313244; border-radius: 6px; padding: 10px 14px; font-family: "JetBrains Mono", monospace; font-size: 13px; color: #f5c2e7; word-break: break-all; margin-bottom: 16px; user-select: all; }
.shutdown-error { background: #2d1b2a; border-left: 3px solid #f38ba8; padding: 8px 12px; margin: 12px 0; color: #f38ba8; font-size: 12px; text-align: left; }
.shutdown-hint { font-size: 11px; color: #6c7086; margin-top: 20px; line-height: 1.5; }

#save-overlay { position: fixed; inset: 0; background: rgba(20,20,30,0.85); display: flex; align-items: center; justify-content: center; z-index: 9998; backdrop-filter: blur(3px); }
.save-modal { background: #1e1e30; border: 1px solid #45475a; border-radius: 12px; padding: 24px 28px; width: 520px; max-width: 92vw; box-shadow: 0 8px 32px rgba(0,0,0,0.4); color: #e0e6f3; }
.save-modal h2 { font-size: 18px; margin-bottom: 16px; color: #cdd6f4; font-weight: 700; }
.save-modal label { display: block; font-size: 11px; color: #6c7086; text-transform: uppercase; letter-spacing: 0.5px; margin: 12px 0 4px; }
.save-modal input[type=text] { width: 100%; background: #11111b; color: #e0e6f3; border: 1px solid #313244; padding: 8px 10px; border-radius: 6px; font-size: 13px; font-family: "JetBrains Mono", monospace; }
.save-modal input[type=text]:focus { outline: none; border-color: #89b4fa; }
.save-kind { display: flex; gap: 10px; flex-wrap: wrap; margin-top: 6px; }
.save-kind label { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; text-transform: none; letter-spacing: normal; color: #cdd6f4; margin: 0; padding: 6px 12px; background: #11111b; border: 1px solid #313244; border-radius: 6px; cursor: pointer; }
.save-kind input { margin: 0; }
.save-buttons { display: flex; gap: 8px; justify-content: flex-end; margin-top: 20px; }
.save-buttons button { padding: 8px 16px; font-size: 13px; }
.save-disabled { opacity: 0.5; cursor: not-allowed; }
.empty button { margin-top: 12px; padding: 10px 20px; font-size: 14px; font-weight: 600; }
.minutes-loading { display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 40px 20px; color: #89dceb; }
.spinner { display: inline-block; width: 40px; height: 40px; border: 4px solid #313244; border-top-color: #89b4fa; border-radius: 50%; animation: spin 0.8s linear infinite; margin-bottom: 16px; }
.minutes-loading-text { font-size: 14px; color: #cdd6f4; font-weight: 500; }
.minutes-loading-sub { font-size: 11px; color: #6c7086; margin-top: 4px; }
@keyframes spin { to { transform: rotate(360deg); } }
.pulse { display: inline-block; width: 11px; height: 11px; border-radius: 50%; background: #a6e3a1; margin-right: 10px; animation: pulse 2s infinite; box-shadow: 0 0 8px #a6e3a1; }
.pulse.paused { background: #f9e2af; animation: none; }
@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }

#toast { position: fixed; top: 60px; left: 50%; transform: translateX(-50%); background: #313244; color: #cdd6f4; padding: 16px 24px; border-radius: 8px; box-shadow: 0 8px 32px rgba(0,0,0,0.6); border: 1px solid #45475a; z-index: 9999; max-width: 80%; opacity: 0; transition: opacity 0.3s; pointer-events: none; }
#toast.visible { opacity: 1; pointer-events: auto; }
#toast.success { border-left: 4px solid #a6e3a1; }
#toast.warning { border-left: 4px solid #f9e2af; }
#toast.error { border-left: 4px solid #f38ba8; }
#toast .toast-title { font-weight: 600; margin-bottom: 6px; }
#toast .toast-body { font-family: "JetBrains Mono", "Consolas", monospace; font-size: 12px; color: #a6adc8; word-break: break-all; }
#toast .toast-actions { display: flex; gap: 8px; margin-top: 10px; }
#toast button { padding: 6px 12px; font-size: 12px; }

#toolbar { display: flex; gap: 16px; padding: 8px 12px; background: #11111b; border-bottom: 1px solid #313244; align-items: center; flex-wrap: wrap; }
.toolbar-group { display: flex; align-items: center; gap: 4px; }
.toolbar-label { color: #6c7086; font-size: 10px; text-transform: uppercase; letter-spacing: 0.5px; padding-right: 6px; border-right: 1px solid #313244; margin-right: 4px; }
.toolbar-group button { padding: 6px 14px; font-size: 13px; }
.toolbar-group .key-hint { color: #6c7086; font-size: 10px; margin-left: 2px; }
button.warning { background: #f9e2af; color: #1e1e2e; }
button.warning:hover { background: #fab387; }
button.success { background: #a6e3a1; color: #1e1e2e; }
button.success:hover { background: #94e2d5; }
</style>
</head>
<body>
<div id="app">
  <header>
    <h1><span class="pulse" id="pulse"></span>Meeting Transcriber</h1>
    <div id="status">接続中...</div>
  </header>
  <div id="toolbar">
    <div class="toolbar-group">
      <span class="toolbar-label">議事録</span>
      <button id="btn-update" title="差分更新 (U)">差分更新<span class="key-hint">U</span></button>
      <button id="btn-full" class="primary" title="フル更新 (F)">フル更新<span class="key-hint">F</span></button>
      <button id="btn-save" title="保存 (S)">保存<span class="key-hint">S</span></button>
    </div>
    <div class="toolbar-group">
      <span class="toolbar-label">録音</span>
      <button id="btn-start" class="primary" title="開始 (G)" style="display:none">開始<span class="key-hint">G</span></button>
      <button id="btn-pause" class="warning" title="一時停止 (P)">一時停止<span class="key-hint">P</span></button>
    </div>
    <div class="toolbar-group" style="margin-left: auto;">
      <button id="btn-reset" class="danger" title="保存してリセット (R)">保存してリセット<span class="key-hint">R</span></button>
      <button id="btn-discard" class="warning" title="保存せずにリセット (D)">破棄リセット<span class="key-hint">D</span></button>
    </div>
  </div>
  <main>
    <div id="left">
      <div class="panel" id="transcript-panel">
        <div class="panel-header"><span>文字起こし</span><span id="transcript-count">0 件</span></div>
        <div class="panel-body" id="transcript-body"><div class="empty">録音待機中...</div></div>
      </div>
      <div class="panel" id="log-panel">
        <div class="panel-header"><span>ログ</span></div>
        <div class="panel-body" id="log-body"></div>
      </div>
    </div>
    <div class="panel" id="minutes-panel">
      <div class="panel-header"><span>議事録プレビュー</span><span id="update-count">更新: 0回</span></div>
      <div class="panel-body"><div id="minutes-content"><div class="empty">議事録はまだ生成されていません<br><button class="primary" onclick="document.getElementById('btn-full').click()">[F] 今すぐ生成</button></div></div></div>
    </div>
    <div class="panel" id="chat-panel">
      <div class="panel-header"><span>AIに聞く</span><span id="chat-typing-area"></span></div>
      <div class="panel-body" id="chat-body"><div class="empty">会議内容について質問できます</div></div>
      <div id="chat-input-row">
        <input type="text" id="chat-input" placeholder="この議論どう思う？など (Enter送信)" autocomplete="off">
        <button id="btn-chat-send" class="primary">送信</button>
      </div>
    </div>
  </main>
  <footer>
    <input type="text" id="command-input" placeholder="議事録への修正指示を入力 (Enter送信)" autocomplete="off">
    <button id="btn-send" class="primary">送信</button>
  </footer>
</div>

<script>
const transcriptBody = document.getElementById('transcript-body');
const logBody = document.getElementById('log-body');
const minutesContent = document.getElementById('minutes-content');
const statusEl = document.getElementById('status');
const transcriptCount = document.getElementById('transcript-count');
const updateCount = document.getElementById('update-count');
const pulse = document.getElementById('pulse');

let transcriptInitialized = false;

function addTranscript(text) {
  if (!transcriptInitialized) { transcriptBody.innerHTML = ''; transcriptInitialized = true; }
  const div = document.createElement('div');
  div.className = 'transcript-entry';
  const m = text.match(/^\\[(\\d{2}:\\d{2}:\\d{2})\\]\\s*(.+)$/);
  if (m) {
    div.innerHTML = '<span class="ts">[' + m[1] + ']</span>' + escapeHtml(m[2]);
  } else {
    div.textContent = text;
  }
  transcriptBody.appendChild(div);
  transcriptBody.scrollTop = transcriptBody.scrollHeight;
}

function addLog(message, level) {
  const div = document.createElement('div');
  div.className = 'log-entry ' + (level || 'info');
  const ts = new Date().toLocaleTimeString('ja-JP', {hour12: false});
  div.innerHTML = '<span class="ts">' + ts + '</span>' + escapeHtml(message);
  logBody.appendChild(div);
  logBody.scrollTop = logBody.scrollHeight;
  while (logBody.children.length > 200) logBody.removeChild(logBody.firstChild);
}

function renderMarkdown(md) {
  let s = md.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  s = s.replace(/```([\\s\\S]*?)```/g, (_, c) => '<pre><code>' + c + '</code></pre>');
  s = s.replace(/`([^`\\n]+)`/g, '<code>$1</code>');
  s = s.replace(/\\*\\*([^*\\n]+)\\*\\*/g, '<strong>$1</strong>');
  s = s.replace(/(^|[^*])\\*([^*\\n]+)\\*(?!\\*)/g, '$1<em>$2</em>');
  const lines = s.split('\\n');
  const out = [];
  let listType = null;
  const closeList = () => { if (listType) { out.push('</' + listType + '>'); listType = null; } };
  for (const line of lines) {
    const h = line.match(/^(#{1,6})\\s+(.+)$/);
    if (h) { closeList(); out.push('<h' + h[1].length + '>' + h[2] + '</h' + h[1].length + '>'); continue; }
    if (/^---+$/.test(line)) { closeList(); out.push('<hr>'); continue; }
    const ul = line.match(/^[\\-\\*]\\s+(.+)$/);
    const ol = line.match(/^\\d+\\.\\s+(.+)$/);
    if (ul) { if (listType !== 'ul') { closeList(); out.push('<ul>'); listType = 'ul'; } out.push('<li>' + ul[1] + '</li>'); continue; }
    if (ol) { if (listType !== 'ol') { closeList(); out.push('<ol>'); listType = 'ol'; } out.push('<li>' + ol[1] + '</li>'); continue; }
    if (line.trim() === '') { closeList(); out.push(''); continue; }
    closeList();
    out.push(line);
  }
  closeList();
  return out.join('\\n').split(/\\n{2,}/).map(block => {
    if (!block.trim()) return '';
    if (/^<(h\\d|ul|ol|pre|hr|blockquote)/.test(block.trim())) return block;
    return '<p>' + block.replace(/\\n/g, '<br>') + '</p>';
  }).join('\\n');
}

let currentMinutesMarkdown = '';
function updateMinutes(markdown) {
  currentMinutesMarkdown = markdown || '';
  if (!markdown) {
    minutesContent.innerHTML = `<div class="empty">議事録はまだ生成されていません<br><button class="primary" onclick="document.getElementById('btn-full').click()">[F] 今すぐ生成</button></div>`;
    return;
  }
  minutesContent.innerHTML = renderMarkdown(markdown);
}

function showMinutesLoading(updateNumber) {
  const subText = updateNumber > 0 ? `（${updateNumber + 1}回目の生成）` : '（初回生成、少し時間がかかります）';
  minutesContent.innerHTML =
    '<div class="minutes-loading">' +
    '<div class="spinner"></div>' +
    '<div class="minutes-loading-text">議事録を生成中...</div>' +
    '<div class="minutes-loading-sub">' + subText + '</div>' +
    '</div>';
}

let isUpdating = false;
function setStatus(s) {
  let text = s.text || '';
  if (typeof s.cumulative_cost_usd === 'number' && s.cumulative_cost_usd > 0) {
    text += ' | コスト: $' + s.cumulative_cost_usd.toFixed(4);
  }
  statusEl.textContent = text;
  transcriptCount.textContent = (s.transcript_count || 0) + ' 件';
  updateCount.textContent = '更新: ' + (s.update_count || 0) + '回';
  if (s.paused) pulse.classList.add('paused'); else pulse.classList.remove('paused');

  // 議事録更新中ならスピナーを表示、終わったら通常表示に戻す
  const nowUpdating = !!s.updating;
  if (nowUpdating && !isUpdating) {
    showMinutesLoading(s.update_count || 0);
  } else if (!nowUpdating && isUpdating) {
    updateMinutes(currentMinutesMarkdown);
  }
  isUpdating = nowUpdating;

  // 録音状態（停止中なら開始ボタン、それ以外は一時停止/再開ボタンを表示）
  const startBtn = document.getElementById('btn-start');
  const pauseBtn = document.getElementById('btn-pause');
  if (s.stopped) {
    startBtn.style.display = '';
    pauseBtn.style.display = 'none';
  } else {
    startBtn.style.display = 'none';
    pauseBtn.style.display = '';
    if (s.paused) {
      pauseBtn.innerHTML = '再開<span class="key-hint">P</span>';
      pauseBtn.classList.remove('warning');
      pauseBtn.classList.add('success');
      pauseBtn.title = '再開 (P)';
    } else {
      pauseBtn.innerHTML = '一時停止<span class="key-hint">P</span>';
      pauseBtn.classList.remove('success');
      pauseBtn.classList.add('warning');
      pauseBtn.title = '一時停止 (P)';
    }
  }
}

const chatBody = document.getElementById('chat-body');
const chatTypingArea = document.getElementById('chat-typing-area');
let chatInitialized = false;

function addChatEntry(entry) {
  if (!chatInitialized) { chatBody.innerHTML = ''; chatInitialized = true; }
  const div = document.createElement('div');
  div.className = 'chat-entry ' + (entry.role || 'user');
  const role = entry.role === 'assistant' ? 'AI' : (entry.role === 'error' ? 'エラー' : 'あなた');
  div.innerHTML = '<div class="role">' + role + '</div><div class="body"></div>';
  div.querySelector('.body').textContent = entry.message;
  chatBody.appendChild(div);
  chatBody.scrollTop = chatBody.scrollHeight;
  chatTypingArea.textContent = '';
}

function setChatTyping(on) {
  chatTypingArea.textContent = on ? '応答中...' : '';
}

function escapeHtml(s) {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

let ws;
let isShutdown = false;
function connect() {
  if (isShutdown) return;
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  ws = new WebSocket(proto + '://' + location.host + '/ws');
  ws.onopen = () => addLog('サーバーに接続しました', 'success');
  ws.onclose = () => {
    if (isShutdown) return;
    addLog('接続が切れました。再接続します...', 'warning');
    setTimeout(connect, 1500);
  };
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    switch (msg.type) {
      case 'init':
        transcriptBody.innerHTML = '';
        transcriptInitialized = msg.transcripts.length > 0;
        if (!transcriptInitialized) transcriptBody.innerHTML = '<div class="empty">録音待機中...</div>';
        msg.transcripts.forEach(addTranscript);
        updateMinutes(msg.minutes);
        setStatus(msg.status);
        chatBody.innerHTML = '';
        chatInitialized = (msg.chat_history || []).length > 0;
        if (!chatInitialized) chatBody.innerHTML = '<div class="empty">会議内容について質問できます</div>';
        (msg.chat_history || []).forEach(addChatEntry);
        break;
      case 'transcript': addTranscript(msg.text); break;
      case 'log': addLog(msg.message, msg.level); break;
      case 'minutes': updateMinutes(msg.markdown); break;
      case 'status': setStatus(msg.status); break;
      case 'chat': addChatEntry(msg.entry); break;
      case 'shutdown_progress': addLog(msg.message, 'warning'); break;
      case 'shutdown_complete': showShutdownModal(msg); break;
      case 'reset': handleReset(msg); break;
    }
  };
}
connect();

function showShutdownModal(info) {
  isShutdown = true;
  const overlay = document.createElement('div');
  overlay.id = 'shutdown-overlay';
  const path = info.output_path || info.session_dir || '(保存されたファイルなし)';
  const errorBlock = info.error
    ? '<div class="shutdown-error">⚠ 保存中にエラーが発生: ' + escapeHtml(info.error) + '</div>'
    : '';
  const transcriptInfo = info.transcript_count > 0
    ? '<div class="shutdown-stat">文字起こし: ' + info.transcript_count + ' 件</div>'
    : '<div class="shutdown-stat">文字起こしなし</div>';
  overlay.innerHTML =
    '<div class="shutdown-modal">' +
    '<div class="shutdown-icon">✔</div>' +
    '<h2>会議を終了しました</h2>' +
    transcriptInfo +
    '<div class="shutdown-path-label">保存先:</div>' +
    '<div class="shutdown-path" id="shutdown-path-text">' + escapeHtml(path) + '</div>' +
    `<button class="primary" onclick="navigator.clipboard.writeText(document.getElementById('shutdown-path-text').textContent); this.textContent='コピーしました'">パスをコピー</button>` +
    errorBlock +
    '<div class="shutdown-hint">このタブは閉じて構いません。再起動するには再度 meeting-transcriber --web を実行してください。</div>' +
    '</div>';
  document.body.appendChild(overlay);
}

async function action(path) {
  try { await fetch('/api/' + path, {method: 'POST'}); }
  catch (e) { addLog('エラー: ' + e.message, 'error'); }
}

document.getElementById('btn-update').onclick = () => action('update?full=false');
document.getElementById('btn-full').onclick = () => action('update?full=true');
document.getElementById('btn-save').onclick = () => openSaveDialog();

async function openSaveDialog() {
  let defaults = {filename: 'meeting', output_dir: '.', has_transcript: false, has_minutes: false};
  try {
    const r = await fetch('/api/save-defaults');
    defaults = await r.json();
  } catch (e) { addLog('保存デフォルト取得失敗: ' + e.message, 'error'); }

  const overlay = document.createElement('div');
  overlay.id = 'save-overlay';
  overlay.addEventListener('click', (e) => { if (e.target === overlay) closeSaveDialog(); });

  const trDis = defaults.has_transcript ? '' : 'class="save-disabled"';
  const mdDis = defaults.has_minutes ? '' : 'class="save-disabled"';
  const bothDis = (defaults.has_transcript && defaults.has_minutes) ? '' : 'class="save-disabled"';
  const defaultKind = defaults.has_minutes && defaults.has_transcript ? 'both' : (defaults.has_minutes ? 'minutes' : 'transcript');

  overlay.innerHTML =
    '<div class="save-modal">' +
    '<h2>保存先を指定</h2>' +
    '<label>ファイル名（拡張子なし）</label>' +
    '<input type="text" id="save-filename" value="' + escapeHtml(defaults.filename) + '">' +
    '<label>出力ディレクトリ（サーバー保存時のみ）</label>' +
    '<input type="text" id="save-path" value="' + escapeHtml(defaults.output_dir) + '">' +
    '<label>対象</label>' +
    '<div class="save-kind">' +
    '<label ' + bothDis + '><input type="radio" name="save-kind" value="both"' + (defaultKind === 'both' ? ' checked' : '') + (bothDis ? ' disabled' : '') + '> 議事録+文字起こし</label>' +
    '<label ' + mdDis + '><input type="radio" name="save-kind" value="minutes"' + (defaultKind === 'minutes' ? ' checked' : '') + (mdDis ? ' disabled' : '') + '> 議事録(.md)のみ</label>' +
    '<label ' + trDis + '><input type="radio" name="save-kind" value="transcript"' + (defaultKind === 'transcript' ? ' checked' : '') + (trDis ? ' disabled' : '') + '> 文字起こし(.txt)のみ</label>' +
    '</div>' +
    '<div class="save-buttons">' +
    '<button onclick="closeSaveDialog()">キャンセル</button>' +
    '<button onclick="doDownload()">ダウンロード</button>' +
    '<button class="primary" onclick="doServerSave()">サーバーに保存</button>' +
    '</div>' +
    '</div>';
  document.body.appendChild(overlay);
}

function closeSaveDialog() {
  const o = document.getElementById('save-overlay');
  if (o) o.remove();
}

function _getSaveKind() {
  const sel = document.querySelector('input[name="save-kind"]:checked');
  return sel ? sel.value : 'transcript';
}

async function doServerSave() {
  const filename = document.getElementById('save-filename').value.trim();
  const output_dir = document.getElementById('save-path').value.trim();
  const kind = _getSaveKind();
  try {
    await fetch('/api/save', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({filename, output_dir, kind}),
    });
    closeSaveDialog();
  } catch (e) { addLog('保存エラー: ' + e.message, 'error'); }
}

async function doDownload() {
  const kind = _getSaveKind();
  const targets = [];
  if (kind === 'both') { targets.push('transcript', 'minutes'); }
  else { targets.push(kind); }
  for (const t of targets) {
    const a = document.createElement('a');
    a.href = '/api/download/' + t;
    a.download = '';
    document.body.appendChild(a);
    a.click();
    a.remove();
  }
  closeSaveDialog();
}
function handleReset(msg) {
  // パネルを初期状態に戻す（次の会議の準備）
  transcriptBody.innerHTML = '<div class="empty">開始ボタンを押して新しい会議を始めてください</div>';
  transcriptInitialized = false;
  currentMinutesMarkdown = '';
  minutesContent.innerHTML = `<div class="empty">議事録はまだ生成されていません<br><button class="primary" onclick="document.getElementById('btn-full').click()">[F] 今すぐ生成</button></div>`;
  chatBody.innerHTML = '<div class="empty">会議内容について質問できます</div>';
  chatInitialized = false;
  transcriptCount.textContent = '0 件';
  updateCount.textContent = '更新: 0回';
  if (msg.error) {
    showToast({title: '保存に失敗しました', body: msg.error, level: 'error', autoHideMs: 0});
    addLog('保存エラー: ' + msg.error, 'error');
  } else if (msg.output_path) {
    showToast({
      title: '保存しました',
      body: msg.output_path,
      level: 'success',
      autoHideMs: 8000,
      copyValue: msg.output_path,
    });
    addLog('保存しました: ' + msg.output_path, 'success');
  } else if (msg.discarded) {
    showToast({
      title: '破棄してリセットしました',
      body: (msg.transcript_count || 0) + '件の文字起こしを破棄しました',
      level: 'warning',
      autoHideMs: 4000,
    });
  } else {
    showToast({
      title: 'リセットしました',
      body: '保存対象がなかったため状態クリアのみ実施しました',
      level: 'warning',
      autoHideMs: 4000,
    });
    addLog('リセットしました（保存対象なし）', 'info');
  }
}

let _toastTimer = null;
function showToast({title, body, level, autoHideMs, copyValue}) {
  let toast = document.getElementById('toast');
  if (!toast) {
    toast = document.createElement('div');
    toast.id = 'toast';
    document.body.appendChild(toast);
  }
  toast.className = level || '';
  // textContent ベースで構築。copyValue / title / body は HTML/属性パースを経由しない
  toast.replaceChildren();
  const titleEl = document.createElement('div');
  titleEl.className = 'toast-title';
  titleEl.textContent = title || '';
  toast.appendChild(titleEl);
  if (body) {
    const bodyEl = document.createElement('div');
    bodyEl.className = 'toast-body';
    bodyEl.textContent = body;
    toast.appendChild(bodyEl);
  }
  const actions = document.createElement('div');
  actions.className = 'toast-actions';
  if (copyValue) {
    const copyBtn = document.createElement('button');
    copyBtn.textContent = 'パスをコピー';
    copyBtn.addEventListener('click', () => {
      navigator.clipboard.writeText(copyValue).then(() => { copyBtn.textContent = 'コピーしました'; });
    });
    actions.appendChild(copyBtn);
  }
  const closeBtn = document.createElement('button');
  closeBtn.textContent = '閉じる';
  closeBtn.addEventListener('click', hideToast);
  actions.appendChild(closeBtn);
  toast.appendChild(actions);
  // 次フレームで visible を付けてフェードイン
  requestAnimationFrame(() => toast.classList.add('visible'));
  if (_toastTimer) clearTimeout(_toastTimer);
  if (autoHideMs && autoHideMs > 0) {
    _toastTimer = setTimeout(hideToast, autoHideMs);
  }
}

function hideToast() {
  const toast = document.getElementById('toast');
  if (!toast) return;
  toast.classList.remove('visible');
  if (_toastTimer) { clearTimeout(_toastTimer); _toastTimer = null; }
}

document.getElementById('btn-pause').onclick = () => action('pause');
document.getElementById('btn-start').onclick = () => action('start');
document.getElementById('btn-reset').onclick = async () => {
  if (confirm('議事録を保存してリセットしますか？')) {
    await action('reset');
    addLog('保存してリセット中...', 'warning');
  }
};
document.getElementById('btn-discard').onclick = async () => {
  if (confirm('現在の文字起こし・議事録を保存せずに破棄してリセットします。よろしいですか？')) {
    await action('discard');
    addLog('破棄リセット中...', 'warning');
  }
};

const cmdInput = document.getElementById('command-input');
async function sendCommand() {
  const text = cmdInput.value.trim();
  if (!text) return;
  cmdInput.value = '';
  try {
    await fetch('/api/command', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({instruction: text}),
    });
  } catch (e) { addLog('エラー: ' + e.message, 'error'); }
}
document.getElementById('btn-send').onclick = sendCommand;
cmdInput.addEventListener('keydown', (e) => { if (e.key === 'Enter') sendCommand(); });

const chatInput = document.getElementById('chat-input');
async function sendChat() {
  const text = chatInput.value.trim();
  if (!text) return;
  chatInput.value = '';
  setChatTyping(true);
  try {
    await fetch('/api/chat', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({message: text}),
    });
  } catch (e) {
    setChatTyping(false);
    addChatEntry({role: 'error', message: e.message});
  }
}
document.getElementById('btn-chat-send').onclick = sendChat;
chatInput.addEventListener('keydown', (e) => { if (e.key === 'Enter') sendChat(); });

document.addEventListener('keydown', (e) => {
  if (e.target === cmdInput || e.target === chatInput) return;
  if (e.key === 'u') action('update?full=false');
  else if (e.key === 'f') action('update?full=true');
  else if (e.key === 's') action('save');   // ショートカット S は従来通り「クイック保存」（既存パスにtranscript_raw.txtを保存）
  else if (e.key === 'p') action('pause');
  else if (e.key === 'g') document.getElementById('btn-start').click();
  else if (e.key === 'r') document.getElementById('btn-reset').click();
  else if (e.key === 'd') document.getElementById('btn-discard').click();
});
</script>
</body>
</html>
"""


class _CommandBody(BaseModel):
    instruction: str


class _ChatBody(BaseModel):
    message: str


class _SaveBody(BaseModel):
    filename: str | None = None
    output_dir: str | None = None
    kind: str = 'transcript'  # 'transcript' / 'minutes' / 'both'


class WebUIServer:
    """Web UIサーバー."""

    def __init__(
        self,
        config: Config,
        recorder: AudioRecorder,
        transcriber: Transcriber,
        updater: MinutesUpdater,
        transcripts: list,
        lock: threading.Lock,
        host: str = '127.0.0.1',
        port: int = 8765,
        open_browser: bool = True,
    ) -> None:
        self.config = config
        self.recorder = recorder
        self.transcriber = transcriber
        self.updater = updater
        self.transcripts = transcripts
        self.lock = lock
        self.host = host
        self.port = port
        self.open_browser = open_browser

        self.start_time = datetime.now()
        self.transcript_index = 0
        self._running = False
        self._updating = False

        self._clients: set[WebSocket] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._server: uvicorn.Server | None = None
        self._shutdown_event: threading.Event = threading.Event()
        self.output_path = None

        # AIチャット用: 議事録生成とは別セッションでClaudeに会議内容を相談する
        self._chat_backend = None
        self._chat_session_id: str | None = None
        self._chat_last_transcript_index = 0
        self._chat_history: list[dict] = []
        self._chat_in_progress = False

        # HTTP Basic 認証 + セッションクッキー
        # config.web_password が None / 空文字 のときは認証オフ（loopback 運用前提）
        self._auth_username = (config.web_username or 'user').strip() or 'user'
        password = (config.web_password or '').strip() if config.web_password else ''
        self._auth_password = password or None
        # サーバープロセス毎に発行する乱数。WebSocket とブラウザ間の認証維持に使う
        self._session_token = secrets.token_urlsafe(32) if self._auth_password else None
        self._auth_cookie_name = 'mt_auth'

        self._allowed_origins = {
            f'http://{self.host}:{self.port}',
            f'http://127.0.0.1:{self.port}',
            f'http://localhost:{self.port}',
        }
        self._allowed_hosts = {
            f'{self.host}:{self.port}',
            f'127.0.0.1:{self.port}',
            f'localhost:{self.port}',
        }

        self.app = self._build_app()

    def _origin_allowed(self, origin: str | None) -> bool:
        return origin is not None and origin in self._allowed_origins

    def _host_allowed(self, host: str | None) -> bool:
        return host is not None and host in self._allowed_hosts

    def _check_basic_auth(self, request: Request) -> bool:
        """Verify Authorization: Basic ヘッダの user:pass を検証する."""
        if not self._auth_password:
            return True
        auth = request.headers.get('authorization', '')
        if not auth.lower().startswith('basic '):
            return False
        try:
            decoded = base64.b64decode(auth[6:]).decode('utf-8')
        except Exception:  # noqa: BLE001
            return False
        user, sep, pwd = decoded.partition(':')
        if not sep:
            return False
        return secrets.compare_digest(user, self._auth_username) and secrets.compare_digest(pwd, self._auth_password)

    def _check_session_cookie(self, request_or_ws) -> bool:  # noqa: ANN001
        if not self._auth_password or self._session_token is None:
            return True
        cookie = request_or_ws.cookies.get(self._auth_cookie_name)
        return cookie is not None and secrets.compare_digest(cookie, self._session_token)

    def _build_app(self) -> FastAPI:
        app = FastAPI(title='Meeting Transcriber')

        @app.middleware('http')
        async def csrf_and_host_guard(request: Request, call_next):  # noqa: ANN001, ANN202
            # DNS rebinding 対策: Host ヘッダ検証
            if not self._host_allowed(request.headers.get('host')):
                return JSONResponse({'error': 'invalid host'}, status_code=421)
            # CSRF 対策: 状態変更系（GET/HEAD/OPTIONS以外）は Origin 検証
            if request.method not in ('GET', 'HEAD', 'OPTIONS'):
                if not self._origin_allowed(request.headers.get('origin')):
                    return JSONResponse({'error': 'origin not allowed'}, status_code=403)
            # 認証チェック: パスワード設定時のみ
            if self._auth_password:
                if not (self._check_session_cookie(request) or self._check_basic_auth(request)):
                    return Response(
                        content='Authentication required',
                        status_code=401,
                        headers={
                            'WWW-Authenticate': 'Basic realm="Meeting Transcriber"',
                            'Content-Type': 'text/plain; charset=utf-8',
                        },
                    )
            response = await call_next(request)
            # 認証成功時はセッションクッキーを発行/更新（WebSocket でも認証維持できるように）
            if self._auth_password and self._session_token is not None:
                response.set_cookie(
                    self._auth_cookie_name,
                    self._session_token,
                    httponly=True,
                    samesite='strict',
                    max_age=60 * 60 * 24,
                    path='/',
                )
            return response

        @app.get('/', response_class=HTMLResponse)
        async def index() -> str:
            return INDEX_HTML

        @app.post('/api/update')
        async def update_minutes(full: bool = False) -> dict:
            self._do_update(full=full)
            return {'ok': True}

        @app.post('/api/save')
        async def save_transcript(body: _SaveBody | None = None) -> dict:
            self._handle_save(body)
            return {'ok': True}

        @app.get('/api/save-defaults')
        async def save_defaults() -> dict:
            from datetime import datetime

            stem = datetime.now().strftime(self.updater.filename_format) if self.updater else 'meeting'
            output_dir = str(self.updater.output_dir) if self.updater else '.'
            has_transcript = False
            has_minutes = False
            with self.lock:
                has_transcript = len(self.transcripts) > 0
            if self.updater is not None:
                has_minutes = bool(self.updater.current_minutes)
            return {
                'filename': stem,
                'output_dir': output_dir,
                'has_transcript': has_transcript,
                'has_minutes': has_minutes,
            }

        @app.get('/api/download/transcript')
        async def download_transcript() -> Response:
            with self.lock:
                text = '\n'.join(str(t) for t in self.transcripts)
            from datetime import datetime

            stem = datetime.now().strftime(self.updater.filename_format) if self.updater else 'transcript'
            return Response(
                content=text,
                media_type='text/plain; charset=utf-8',
                headers={'Content-Disposition': f'attachment; filename="{stem}.txt"'},
            )

        @app.get('/api/download/minutes')
        async def download_minutes() -> Response:
            md = self.updater.get_current_minutes() if self.updater else ''
            from datetime import datetime

            stem = datetime.now().strftime(self.updater.filename_format) if self.updater else 'minutes'
            return Response(
                content=md,
                media_type='text/markdown; charset=utf-8',
                headers={'Content-Disposition': f'attachment; filename="{stem}.md"'},
            )

        @app.post('/api/pause')
        async def toggle_pause() -> dict:
            self._handle_pause()
            return {'ok': True}

        @app.post('/api/start')
        async def start_recording() -> dict:
            self._handle_start()
            return {'ok': True}

        @app.post('/api/reset')
        async def reset_session() -> dict:
            threading.Thread(target=self._do_reset, args=(True,), daemon=True).start()
            return {'ok': True}

        @app.post('/api/discard')
        async def discard_session() -> dict:
            threading.Thread(target=self._do_reset, args=(False,), daemon=True).start()
            return {'ok': True}

        @app.post('/api/command')
        async def send_command(body: _CommandBody) -> dict:
            self._handle_command(body.instruction)
            return {'ok': True}

        @app.post('/api/chat')
        async def send_chat(body: _ChatBody) -> dict:
            self._handle_chat(body.message)
            return {'ok': True}

        @app.post('/api/quit')
        async def quit_app() -> dict:
            threading.Thread(target=self._shutdown, daemon=True).start()
            return {'ok': True}

        @app.websocket('/ws')
        async def websocket_endpoint(ws: WebSocket) -> None:
            # Cross-Origin WebSocket Hijacking 対策
            if not self._origin_allowed(ws.headers.get('origin')):
                await ws.close(code=1008)
                return
            if not self._host_allowed(ws.headers.get('host')):
                await ws.close(code=1008)
                return
            # 認証: ブラウザは ws upgrade で Basic auth を送らないので、Cookie で検証する
            # (HTTP リクエスト時の middleware で set_cookie 済みのはず)
            if self._auth_password and not self._check_session_cookie(ws):
                await ws.close(code=1008)
                return
            await ws.accept()
            self._clients.add(ws)
            try:
                with self.lock:
                    transcripts_snapshot = [str(t) for t in self.transcripts]
                await ws.send_json(
                    {
                        'type': 'init',
                        'transcripts': transcripts_snapshot,
                        'minutes': self.updater.get_current_minutes() if self.updater else '',
                        'status': self._build_status(),
                        'chat_history': list(self._chat_history),
                    }
                )
                while True:
                    await ws.receive_text()
            except WebSocketDisconnect:
                pass
            finally:
                self._clients.discard(ws)

        @app.on_event('startup')
        async def on_startup() -> None:
            self._loop = asyncio.get_running_loop()
            self._start_workers()
            if self.open_browser:
                url = f'http://{self.host}:{self.port}'
                threading.Thread(target=lambda: webbrowser.open(url), daemon=True).start()
            asyncio.create_task(self._status_ticker())

        return app

    def _build_status(self) -> dict:
        with self.lock:
            transcript_count = len(self.transcripts)
        elapsed = datetime.now() - self.start_time
        elapsed_str = str(elapsed).split('.')[0]
        stopped = not self.recorder.is_recording()
        if stopped:
            state = '待機中'
        elif self.recorder.is_paused():
            state = '一時停止中'
        elif self._updating:
            state = '更新中'
        else:
            state = '録音中'
        cost = self._collect_cumulative_cost()
        return {
            'text': f'{state} | 経過: {elapsed_str} | 発言: {transcript_count}件',
            'transcript_count': transcript_count,
            'update_count': self.updater.update_count if self.updater else 0,
            'paused': self.recorder.is_paused(),
            'stopped': stopped,
            'cumulative_cost_usd': cost,
            'updating': self._updating,
        }

    def _collect_cumulative_cost(self) -> float:
        """議事録生成とチャットの両バックエンドの累計コストを合算する."""
        total = 0.0
        backends = []
        if self.updater is not None and self.updater.generator is not None:
            backends.append(self.updater.generator.backend)
        if self._chat_backend is not None:
            backends.append(self._chat_backend)
        for b in backends:
            try:
                total += float(b.cumulative_cost_usd)
            except (AttributeError, TypeError, ValueError):
                pass
        return total

    def _broadcast(self, event: dict) -> None:
        """別スレッドからWebSocketクライアントへブロードキャスト."""
        if self._loop is None or self._loop.is_closed():
            return
        asyncio.run_coroutine_threadsafe(self._broadcast_async(event), self._loop)

    async def _broadcast_async(self, event: dict) -> None:
        dead = []
        for ws in self._clients:
            try:
                await ws.send_json(event)
            except Exception:  # noqa: BLE001
                dead.append(ws)
        for ws in dead:
            self._clients.discard(ws)

    def _log(self, message: str, level: str = 'info') -> None:
        self._broadcast({'type': 'log', 'message': message, 'level': level})

    def _broadcast_status(self) -> None:
        self._broadcast({'type': 'status', 'status': self._build_status()})

    def _broadcast_minutes(self) -> None:
        if self.updater:
            self._broadcast({'type': 'minutes', 'markdown': self.updater.get_current_minutes()})

    async def _status_ticker(self) -> None:
        while self._running:
            await asyncio.sleep(2)
            self._broadcast_status()

    def _start_workers(self) -> None:
        self._running = True
        self.recorder.start()
        self._log('録音を開始しました', 'success')
        self._log(
            f'ステップ: {self.config.step_duration}秒 | ウィンドウ: {self.config.window_duration}秒',
            'info',
        )
        if self.config.transcript_only:
            self._log('文字起こしのみモード（議事録は生成されません）', 'warning')
        elif self.config.auto_update:
            self._log(f'自動更新: {self.config.update_interval}秒間隔', 'info')

        threading.Thread(target=self._transcribe_loop, daemon=True).start()

        if self.config.auto_update and not self.config.transcript_only:
            threading.Thread(target=self._auto_update_loop, daemon=True).start()

    def _transcribe_loop(self) -> None:
        from meeting_transcriber.config import TranscriptEntry

        while self._running:
            audio = self.recorder.get_audio_chunk(timeout=0.5)
            if audio is None:
                continue
            try:
                text = self.transcriber.transcribe(audio)
            except Exception as e:  # noqa: BLE001
                self._log(f'文字起こしエラー: {e}', 'error')
                continue
            if not text:
                continue
            timestamp = datetime.now()
            entry = TranscriptEntry(timestamp=timestamp, text=text, index=self.transcript_index)
            with self.lock:
                self.transcripts.append(entry)
                self.transcript_index += 1
            self._broadcast({'type': 'transcript', 'text': str(entry)})

            # ホットワード検出: マッチしたら AI チャットへ自動投稿
            question = self._extract_hotword_question(text)
            if question is not None:
                self._log(f'ホットワード検出: 「{question}」をAIへ質問', 'info')
                self._handle_chat(question)

    def _extract_hotword_question(self, text: str) -> str | None:
        """文字起こし text からホットワード以降の質問テキストを抽出する.

        マッチしない、無効化されている、文字起こし専用モード、質問が短すぎる場合は None。
        複数ホットワードがマッチした場合は最も後ろにある hit を採用（直前を文脈とみなす）。
        """
        if not getattr(self.config, 'hotwords_enabled', False):
            return None
        if self.config.transcript_only:
            return None
        hotwords = getattr(self.config, 'hotwords', None) or []
        if not hotwords:
            return None

        lower_text = text.lower()
        best_idx = -1
        best_word_len = 0
        for word in hotwords:
            if not word:
                continue
            idx = lower_text.find(word.lower())
            if idx == -1:
                continue
            # より後ろのホットワードを優先（質問は会話の途中で出る想定）
            if idx > best_idx:
                best_idx = idx
                best_word_len = len(word)

        if best_idx < 0:
            return None

        question = text[best_idx + best_word_len :].strip(' 　、。.!！?？\n')
        min_len = getattr(self.config, 'hotword_min_question_length', 3)
        if len(question) < min_len:
            return None
        return question

    def _auto_update_loop(self) -> None:
        import time

        while self._running:
            time.sleep(self.config.update_interval)
            if not self._running:
                break
            if self._updating or self.recorder.is_paused():
                continue
            with self.lock:
                new_count = len(self.transcripts) - self.updater.last_update_index
            if new_count == 0:
                continue
            self._log(f'自動更新を開始 (新規: {new_count}件)', 'info')
            self._do_update(full=False)

    def _do_update(self, full: bool = False) -> None:
        if self.config.transcript_only:
            self._log('文字起こしのみモードのため議事録は生成されません', 'warning')
            return
        # check と set を lock 内で原子的に行う（自動更新と手動更新の並走対策）
        with self.lock:
            if self._updating:
                self._log('更新中です', 'warning')
                return
            transcripts_copy = list(self.transcripts)
            if not transcripts_copy:
                self._log('まだ文字起こしがありません', 'warning')
                return
            self._updating = True
        update_type = 'フル更新' if full else '差分更新'
        new_count = len(transcripts_copy) - self.updater.last_update_index
        self._log(
            f'{update_type}中... ({self.updater.update_count + 1}回目, 新規: {new_count}件)',
            'info',
        )
        self._broadcast_status()
        threading.Thread(
            target=self._update_task,
            args=(transcripts_copy, full),
            daemon=True,
        ).start()

    def _update_task(self, transcripts: list, full: bool) -> None:
        try:
            result = self.updater.update(transcripts, full=full)
            if result.success:
                cost_str = self._format_last_cost(self.updater.generator.backend if self.updater.generator else None)
                self._log(f'更新完了 | 新規: {result.new_entries_count}件{cost_str}', 'success')
                self._broadcast_minutes()
            else:
                self._log(f'更新失敗: {result.error}', 'error')
        finally:
            self._updating = False
            self._broadcast_status()

    @staticmethod
    def _format_last_cost(backend: object | None) -> str:
        """直近呼び出しコストをログ表示用の文字列にする（無効値は空文字）."""
        if backend is None:
            return ''
        try:
            cost = float(getattr(backend, 'last_cost_usd', 0.0))
        except (TypeError, ValueError):
            return ''
        if cost <= 0:
            return ''
        return f' | コスト: ${cost:.4f}'

    def _handle_save(self, body=None) -> None:  # noqa: ANN001
        """文字起こしと議事録を保存する.

        body=None or body にカスタム指定がなければ既存挙動（updater.save_transcript_only）。
        body.filename / body.output_dir 指定時は任意のパスへ書き出す。
        body.kind: 'transcript' / 'minutes' / 'both'
        """
        with self.lock:
            transcripts_copy = list(self.transcripts)

        kind = (body.kind if body is not None else 'transcript') or 'transcript'
        wants_transcript = kind in ('transcript', 'both')
        wants_minutes = kind in ('minutes', 'both')

        if wants_transcript and not transcripts_copy:
            self._log('まだ文字起こしがありません', 'warning')
            if not wants_minutes:
                return
        if wants_minutes and (self.updater is None or not self.updater.current_minutes):
            self._log('議事録がまだ生成されていません', 'warning')
            if not wants_transcript or not transcripts_copy:
                return

        # カスタム指定なしなら既存挙動（後方互換、ショートカット S のクイック保存）
        if body is None or (not body.filename and not body.output_dir):
            try:
                if transcripts_copy:
                    path = self.updater.save_transcript_only(transcripts_copy)
                    self._log(f'保存しました: {path}', 'success')
            except Exception as e:  # noqa: BLE001
                self._log(f'保存エラー: {e}', 'error')
            return

        # カスタム保存
        from pathlib import Path as _Path

        # ファイル名はパストラバーサル攻撃を防ぐため厳格にサニタイズ
        # (output_dir は localhost のユーザー自身が任意指定する用途なので制限しない)
        stem = body.filename or self.start_time.strftime(self.updater.filename_format)
        if '/' in stem or '\\' in stem or '..' in stem or not _SAFE_FILENAME_RE.match(stem):
            self._log(
                f'保存エラー: ファイル名が無効です (英数/日本語/-_. のみ128字以内): {stem!r}',
                'error',
            )
            return

        try:
            target_dir = _Path(body.output_dir).expanduser().resolve() if body.output_dir else self.updater.output_dir
            target_dir.mkdir(parents=True, exist_ok=True)

            saved = []
            if wants_transcript and transcripts_copy:
                txt_path = target_dir / f'{stem}.txt'
                txt_path.write_text('\n'.join(str(t) for t in transcripts_copy), encoding='utf-8')
                saved.append(str(txt_path))
            if wants_minutes and self.updater.current_minutes:
                md_path = target_dir / f'{stem}.md'
                md_path.write_text(self.updater.current_minutes, encoding='utf-8')
                saved.append(str(md_path))

            if saved:
                self._log(f'保存しました: {" | ".join(saved)}', 'success')
            else:
                self._log('保存対象が空でした', 'warning')
        except Exception as e:  # noqa: BLE001
            self._log(f'保存エラー: {e}', 'error')

    def _handle_pause(self) -> None:
        if not self.recorder.is_recording():
            self._log('録音が停止中です。開始ボタンを押してください', 'warning')
            return
        if self.recorder.is_paused():
            self.recorder.resume()
            self._log('録音を再開しました', 'success')
        else:
            self.recorder.pause()
            self._log('録音を一時停止しました', 'warning')
        self._broadcast_status()

    def _handle_start(self) -> None:
        """停止中なら録音を開始、一時停止中なら再開する."""
        if self.recorder.is_recording():
            if self.recorder.is_paused():
                self.recorder.resume()
                self._log('録音を再開しました', 'success')
            else:
                self._log('既に録音中です', 'warning')
            self._broadcast_status()
            return
        # 新しい会議としてタイマーをリセット
        self.start_time = datetime.now()
        # この時点で updater を新しい start_time で作り直し、新セッションディレクトリにする
        # （前回の transcripts/minutes/state は _do_reset で既にクリア済み or 初回起動）
        if self.updater is not None and self._running:
            try:
                self._reset_updater()
            except Exception as e:  # noqa: BLE001
                logging.warning('updater リセット失敗: %s', e)
        if not self._running:
            # 初回起動の場合のみワーカースレッドも立ち上げる（recorder.start もここで呼ばれる）
            self._start_workers()
        else:
            # 既にワーカーが動いていればレコーダーだけ再起動すれば transcribe_loop が拾い始める
            self.recorder.start()
            self._log('録音を開始しました', 'success')
        self._broadcast_status()

    def _do_reset(self, save: bool = True) -> None:
        """状態をクリアし次の会議に備える。save=True なら保存してから、save=False なら破棄してリセット."""
        # 録音停止
        try:
            self.recorder.stop()
        except Exception:  # noqa: BLE001
            pass

        # スナップショット取得
        with self.lock:
            transcripts_copy = list(self.transcripts)

        # 保存（save=True かつ transcripts があれば）
        saved_path: str | None = None
        save_error: str | None = None
        if save and transcripts_copy and self.updater is not None:
            try:
                if self.config.transcript_only:
                    saved_path = str(self.updater.save_transcript_only(transcripts_copy))
                else:
                    if not self.updater.current_minutes:
                        self.updater.update(transcripts_copy, full=True)
                    saved_path = str(self.updater.save(transcripts_copy))
            except Exception as e:  # noqa: BLE001
                logging.error('リセット時の保存エラー: %s', e)
                save_error = str(e)
        elif not save and transcripts_copy:
            self._log(f'{len(transcripts_copy)}件の文字起こしを破棄しました', 'warning')

        # 状態クリア
        with self.lock:
            self.transcripts.clear()
            self.transcript_index = 0
        self._chat_history = []
        self._chat_last_transcript_index = 0
        self._updating = False
        self.output_path = None
        # updater は次の _handle_start で新しい start_time で作り直す

        # backend の session_id を新規発行（prompt cache を新会議扱いに）
        for b in self._all_backends():
            try:
                b.reset_context()
            except Exception:  # noqa: BLE001
                pass

        if save_error:
            self._log(f'保存エラー: {save_error}', 'error')

        # フロントへ通知（output_path が None なら「保存対象なし」扱い）
        self._broadcast(
            {
                'type': 'reset',
                'output_path': saved_path,
                'transcript_count': len(transcripts_copy),
                'discarded': not save and bool(transcripts_copy),
                'error': save_error,
            }
        )
        self._broadcast_status()

    def _reset_updater(self) -> None:
        """MinutesUpdater を新しい開始時刻で作り直す（新セッション扱い）."""
        if self.updater is None:
            return
        from meeting_transcriber.minutes import MinutesUpdater

        old = self.updater
        self.updater = MinutesUpdater(
            generator=old.generator,
            output_dir=old.output_dir,
            template=old.template,
            start_time=self.start_time,
            filename_format=old.filename_format,
            version_history=old.version_history,
            simple_mode=old.simple_mode,
        )

    def _all_backends(self) -> list:
        backends = []
        if self.updater is not None and self.updater.generator is not None:
            backends.append(self.updater.generator.backend)
        if self._chat_backend is not None:
            backends.append(self._chat_backend)
        return backends

    def _handle_command(self, instruction: str) -> None:
        if self.config.transcript_only:
            self._log('文字起こしのみモードのため指示を受け付けません', 'warning')
            return
        if not self.updater.current_minutes:
            self._log('議事録がまだ生成されていません。先に更新してください', 'warning')
            return
        with self.lock:
            if self._updating:
                self._log('更新中です。完了をお待ちください', 'warning')
                return
            self._updating = True
        self._log(f'指示を送信中: {instruction}', 'info')
        self._broadcast_status()
        threading.Thread(
            target=self._command_task,
            args=(instruction,),
            daemon=True,
        ).start()

    def _handle_chat(self, message: str) -> None:
        if self.config.transcript_only:
            self._log('文字起こしのみモードのためAIチャットは無効です', 'warning')
            return
        message = message.strip()
        if not message:
            return
        if self._chat_in_progress:
            self._log('AIチャット応答中です', 'warning')
            return
        self._chat_in_progress = True
        threading.Thread(target=self._chat_task, args=(message,), daemon=True).start()

    def _ensure_chat_backend(self) -> None:
        """チャット専用のBackendを遅延初期化する（議事録生成とは別セッション）."""
        if self._chat_backend is not None:
            return
        from meeting_transcriber.backends import get_backend

        self._chat_session_id = str(uuid.uuid4())
        self._chat_backend = get_backend(self.config, session_id=self._chat_session_id)

    def _build_chat_prompt(self, message: str, new_transcripts_text: str, is_first: bool) -> str:
        """チャットプロンプトを構築する.

        初回: 会議の役割説明 + 文字起こし全体 + 質問
        2回目以降: 新規発言（あれば）+ 質問のみ。残りはClaudeのセッション履歴に任せる。
        """
        if is_first:
            transcript_block = new_transcripts_text or '（まだ発言がありません）'
            return (
                'あなたは会議に同席しているAIアシスタントです。'
                '以下の会議の文字起こしを踏まえて、ユーザーの質問や相談に簡潔に答えてください。'
                '議事録の生成や修正は別系統で行われるので、ここでは議事録を出力する必要はありません。\n\n'
                f'【会議の文字起こし】\n{transcript_block}\n\n'
                f'【ユーザーからの質問】\n{message}'
            )
        if new_transcripts_text:
            return f'【その後の新しい発言】\n{new_transcripts_text}\n\n【ユーザーからの質問】\n{message}'
        return message

    _CHAT_SYSTEM_PROMPT = (
        'あなたは会議に同席しているAIアシスタントです。'
        'ユーザーは会議の最中に思いついた疑問や相談をしてきます。'
        '日本語で、簡潔かつ具体的に回答してください。'
        '議事録の生成や修正は別系統で行われるので、ここでは議事録を出力しないでください。'
        '会議内容と直接関係ない一般的な質問（例: 用語の意味、最新情報、計算など）にも自然に答えてください。'
        '最新情報や事実確認が必要な質問では web_search ツールを使って検索してください。'
        '会議の文脈や常識で答えられる質問では検索しないでください。'
        '検索結果を引用するときは URL を明示してください。'
    )

    def _chat_task(self, message: str) -> None:
        try:
            self._ensure_chat_backend()

            with self.lock:
                transcripts_snapshot = list(self.transcripts)

            new_entries = transcripts_snapshot[self._chat_last_transcript_index :]
            new_text = '\n'.join(str(t) for t in new_entries)
            self._chat_last_transcript_index = len(transcripts_snapshot)

            user_entry = {'role': 'user', 'message': message}
            self._chat_history.append(user_entry)
            self._broadcast({'type': 'chat', 'entry': user_entry})

            # OpenAI 互換 backend なら multi-turn messages を直接組み立てて投げる
            backend = self._chat_backend
            if hasattr(backend, 'chat_with_tools'):
                response = self._invoke_chat_with_history(message, new_text, transcripts_snapshot)
            else:
                # 単発 prompt 経路（Claude CLI など session_id を持つ backend 用）
                is_first = len(self._chat_history) == 1
                prompt = self._build_chat_prompt(message, new_text, is_first)
                response = backend.generate(prompt)

            assistant_entry = {'role': 'assistant', 'message': response}
            self._chat_history.append(assistant_entry)
            self._broadcast({'type': 'chat', 'entry': assistant_entry})
        except Exception as e:  # noqa: BLE001
            error_entry = {'role': 'error', 'message': f'エラー: {e}'}
            self._chat_history.append(error_entry)
            self._broadcast({'type': 'chat', 'entry': error_entry})
        finally:
            self._chat_in_progress = False

    def _invoke_chat_with_history(
        self,
        user_message: str,
        new_transcripts_text: str,
        transcripts_snapshot: list,
    ) -> str:
        """会話履歴 + 文字起こしコンテキストを multi-turn messages で送って tool calling ループを回す."""
        from meeting_transcriber.tools import TOOL_DEFINITIONS

        # システム: チャット用の役割。議事録 system_prompt は使わない
        # 文字起こしも 1 つの system にまとめる（vLLM/Qwen で複数 system が 400 を返すケース対策）
        is_first_turn = len([h for h in self._chat_history if h.get('role') == 'assistant']) == 0
        if is_first_turn:
            transcript_block = '\n'.join(str(t) for t in transcripts_snapshot) or '（まだ発言がありません）'
            system_content = f'{self._CHAT_SYSTEM_PROMPT}\n\n【現時点の会議文字起こし】\n{transcript_block}'
        else:
            extra = f'\n\n【前回応答以降の新規発言】\n{new_transcripts_text}' if new_transcripts_text else ''
            system_content = f'{self._CHAT_SYSTEM_PROMPT}{extra}'
        messages: list[dict] = [{'role': 'system', 'content': system_content}]

        # これまでの会話を user/assistant で復元（error / 空メッセージは除外、最新 user は別途追加するので除外）
        prior = [
            h
            for h in self._chat_history[:-1]
            if h.get('role') in ('user', 'assistant') and (h.get('message') or '').strip()
        ]
        for h in prior:
            messages.append({'role': h['role'], 'content': h['message']})

        # 今回の user 質問
        messages.append({'role': 'user', 'content': user_message})

        def _on_tool_call(name: str, args_json: str, result: str) -> None:
            preview = result[:200].replace('\n', ' ')
            self._log(f'ツール実行: {name}({args_json}) → {preview}...', 'info')

        def _on_iteration(**info) -> None:
            self._log(
                f'チャット iter={info["iteration"]} '
                f'tool_calls={info["n_tool_calls"]} '
                f'content={info["content_len"]}文字 '
                f'reasoning={info["reasoning_len"]}文字 '
                f'finish={info["finish_reason"]}',
                'info',
            )

        result = self._chat_backend.chat_with_tools(
            messages=messages,
            tools=TOOL_DEFINITIONS,
            on_tool_call=_on_tool_call,
            on_iteration=_on_iteration,
        )
        if not result:
            self._log(
                'AI から空の応答が返りました。同じ質問でもう一度試すか、質問を言い換えてみてください',
                'warning',
            )
            result = '(モデルが空の応答を返しました。もう一度試してください)'
        return result

    def _command_task(self, instruction: str) -> None:
        prompt = f"""あなたは議事録修正アシスタントです。
ユーザーの指示に従って議事録を修正してください。

【ユーザーの指示】
{instruction}

【現在の議事録】
{self.updater.current_minutes}

【出力】
修正後の議事録全体をMarkdown形式で出力してください。余計な説明は不要です。"""
        try:
            result = self.updater.generator.backend.generate(prompt)
            self.updater.current_minutes = result
            self._broadcast_minutes()
            self._log('議事録を修正しました', 'success')
        except Exception as e:  # noqa: BLE001
            self._log(f'エラー: {e}', 'error')
        finally:
            self._updating = False
            self._broadcast_status()

    def _force_exit_after_timeout(self, timeout: float) -> None:
        """指定秒数経っても落ちきらない場合に強制終了する."""
        import os
        import time

        time.sleep(timeout)
        if self._server is not None and not getattr(self._server, 'force_exit', False):
            print(f'\n{timeout}秒経過したので強制終了します', flush=True)
            os._exit(0)

    def _shutdown(self) -> None:
        """終了処理（別スレッドから呼ばれる）."""
        if self._shutdown_event.is_set():
            return
        self._shutdown_event.set()
        self._running = False

        # フロントに「終了処理中」を通知
        self._broadcast({'type': 'shutdown_progress', 'message': '終了処理中...'})

        try:
            self.recorder.stop()
        except Exception:  # noqa: BLE001
            pass

        with self.lock:
            transcripts_copy = list(self.transcripts)

        save_error = None
        if transcripts_copy:
            self._broadcast({'type': 'shutdown_progress', 'message': '議事録を保存中...'})
            try:
                if self.config.transcript_only:
                    self.output_path = self.updater.save_transcript_only(transcripts_copy)
                else:
                    if not self.updater.current_minutes:
                        self.updater.update(transcripts_copy, full=True)
                    else:
                        new_transcripts = self.updater.get_new_transcripts(transcripts_copy)
                        if new_transcripts:
                            self.updater.update(transcripts_copy, full=False)
                    self.output_path = self.updater.save(transcripts_copy)
            except Exception as e:  # noqa: BLE001
                logging.error('保存エラー: %s', e)
                save_error = str(e)

        # 保存完了をフロントに通知（WebSocket切断前に最後に1回ブロードキャスト）
        self._broadcast(
            {
                'type': 'shutdown_complete',
                'output_path': str(self.output_path) if self.output_path else None,
                'session_dir': str(self.updater.session_dir) if hasattr(self.updater, 'session_dir') else None,
                'transcript_count': len(transcripts_copy),
                'error': save_error,
            }
        )

        # ブロードキャストを送り切るため少し待ってからサーバー停止
        import time

        time.sleep(0.8)

        if self._server is not None:
            self._server.should_exit = True

    def run(self) -> None:
        """サーバーを起動する（ブロッキング）."""
        config = uvicorn.Config(
            self.app,
            host=self.host,
            port=self.port,
            log_level='warning',
            access_log=False,
        )

        outer = self

        class _NoSignalServer(uvicorn.Server):
            def install_signal_handlers(self) -> None:
                # uvicorn の上書きを抑止して自前ハンドラを使う
                return

        self._server = _NoSignalServer(config)

        # 1回目: 自前の _shutdown を別スレッドで起動（議事録保存などを実行）
        # 2回目: 即座に強制終了
        sigint_count = {'n': 0}

        def _signal_handler(_signum, _frame) -> None:
            sigint_count['n'] += 1
            if sigint_count['n'] >= 2:
                print('\n強制終了します', flush=True)
                import os

                os._exit(130)
            print('\n終了処理中... (もう一度 Ctrl-C で強制終了)', flush=True)
            threading.Thread(target=outer._force_exit_after_timeout, args=(8.0,), daemon=True).start()  # noqa: SLF001
            threading.Thread(target=outer._shutdown, daemon=True).start()  # noqa: SLF001

        try:
            signal.signal(signal.SIGINT, _signal_handler)
            signal.signal(signal.SIGTERM, _signal_handler)
        except ValueError:
            pass

        print(f'Web UI: http://{self.host}:{self.port}')
        if self._auth_password:
            print(f'  認証: HTTP Basic 有効 (user: {self._auth_username})')
        else:
            print('  認証: 無効（config.web_password 未設定）')
            if self.host not in ('127.0.0.1', 'localhost'):
                print(f'  ⚠ {self.host} で LAN 公開しているのに認証が無効です。config.web_password を設定してください')
        self._server.run()

        if self.output_path:
            print(f'\n出力: {self.output_path}')
