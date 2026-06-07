"""FastAPIベースのWeb UIサーバー."""

from __future__ import annotations

import asyncio
import logging
import signal
import threading
import uuid
import webbrowser
from datetime import datetime
from typing import TYPE_CHECKING

import uvicorn
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

if TYPE_CHECKING:
    from meeting_transcriber.audio import AudioRecorder
    from meeting_transcriber.config import Config
    from meeting_transcriber.minutes import MinutesUpdater
    from meeting_transcriber.transcriber import Transcriber

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

.empty { color: #6c7086; font-style: italic; text-align: center; padding: 20px; }
.pulse { display: inline-block; width: 11px; height: 11px; border-radius: 50%; background: #a6e3a1; margin-right: 10px; animation: pulse 2s infinite; box-shadow: 0 0 8px #a6e3a1; }
.pulse.paused { background: #f9e2af; animation: none; }
@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }

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
      <button id="btn-pause" class="warning" title="一時停止 (P)">一時停止<span class="key-hint">P</span></button>
    </div>
    <div class="toolbar-group" style="margin-left: auto;">
      <button id="btn-quit" class="danger" title="終了 (Q)">終了<span class="key-hint">Q</span></button>
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
      <div class="panel-body"><div id="minutes-content"><div class="empty">議事録はまだ生成されていません</div></div></div>
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

function updateMinutes(markdown) {
  if (!markdown) {
    minutesContent.innerHTML = '<div class="empty">議事録はまだ生成されていません</div>';
    return;
  }
  minutesContent.innerHTML = renderMarkdown(markdown);
}

function setStatus(s) {
  let text = s.text || '';
  if (typeof s.cumulative_cost_usd === 'number' && s.cumulative_cost_usd > 0) {
    text += ' | コスト: $' + s.cumulative_cost_usd.toFixed(4);
  }
  statusEl.textContent = text;
  transcriptCount.textContent = (s.transcript_count || 0) + ' 件';
  updateCount.textContent = '更新: ' + (s.update_count || 0) + '回';
  if (s.paused) pulse.classList.add('paused'); else pulse.classList.remove('paused');

  // 一時停止/再開ボタンのトグル
  const pauseBtn = document.getElementById('btn-pause');
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
function connect() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  ws = new WebSocket(proto + '://' + location.host + '/ws');
  ws.onopen = () => addLog('サーバーに接続しました', 'success');
  ws.onclose = () => { addLog('接続が切れました。再接続します...', 'warning'); setTimeout(connect, 1500); };
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
    }
  };
}
connect();

async function action(path) {
  try { await fetch('/api/' + path, {method: 'POST'}); }
  catch (e) { addLog('エラー: ' + e.message, 'error'); }
}

document.getElementById('btn-update').onclick = () => action('update?full=false');
document.getElementById('btn-full').onclick = () => action('update?full=true');
document.getElementById('btn-save').onclick = () => action('save');
document.getElementById('btn-pause').onclick = () => action('pause');
document.getElementById('btn-quit').onclick = async () => {
  if (confirm('議事録を保存して終了しますか？')) {
    await action('quit');
    addLog('終了処理中...', 'warning');
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
  else if (e.key === 's') action('save');
  else if (e.key === 'p') action('pause');
  else if (e.key === 'q') document.getElementById('btn-quit').click();
});
</script>
</body>
</html>
"""


class _CommandBody(BaseModel):
    instruction: str


class _ChatBody(BaseModel):
    message: str


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
            return await call_next(request)

        @app.get('/', response_class=HTMLResponse)
        async def index() -> str:
            return INDEX_HTML

        @app.post('/api/update')
        async def update_minutes(full: bool = False) -> dict:
            self._do_update(full=full)
            return {'ok': True}

        @app.post('/api/save')
        async def save_transcript() -> dict:
            self._handle_save()
            return {'ok': True}

        @app.post('/api/pause')
        async def toggle_pause() -> dict:
            self._handle_pause()
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
        if self.recorder.is_paused():
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
            'cumulative_cost_usd': cost,
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
        if self._updating:
            self._log('更新中です', 'warning')
            return
        with self.lock:
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

    def _handle_save(self) -> None:
        with self.lock:
            transcripts_copy = list(self.transcripts)
        if not transcripts_copy:
            self._log('まだ文字起こしがありません', 'warning')
            return
        try:
            path = self.updater.save_transcript_only(transcripts_copy)
            self._log(f'保存しました: {path}', 'success')
        except Exception as e:  # noqa: BLE001
            self._log(f'保存エラー: {e}', 'error')

    def _handle_pause(self) -> None:
        if self.recorder.is_paused():
            self.recorder.resume()
            self._log('録音を再開しました', 'success')
        else:
            self.recorder.pause()
            self._log('録音を一時停止しました', 'warning')
        self._broadcast_status()

    def _handle_command(self, instruction: str) -> None:
        if self.config.transcript_only:
            self._log('文字起こしのみモードのため指示を受け付けません', 'warning')
            return
        if not self.updater.current_minutes:
            self._log('議事録がまだ生成されていません。先に更新してください', 'warning')
            return
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

    def _chat_task(self, message: str) -> None:
        try:
            self._ensure_chat_backend()

            with self.lock:
                transcripts_snapshot = list(self.transcripts)

            is_first = self._chat_last_transcript_index == 0 and not self._chat_history
            new_entries = transcripts_snapshot[self._chat_last_transcript_index :]
            new_text = '\n'.join(str(t) for t in new_entries)
            self._chat_last_transcript_index = len(transcripts_snapshot)

            user_entry = {'role': 'user', 'message': message}
            self._chat_history.append(user_entry)
            self._broadcast({'type': 'chat', 'entry': user_entry})

            prompt = self._build_chat_prompt(message, new_text, is_first)
            response = self._chat_backend.generate(prompt)

            assistant_entry = {'role': 'assistant', 'message': response}
            self._chat_history.append(assistant_entry)
            self._broadcast({'type': 'chat', 'entry': assistant_entry})
        except Exception as e:  # noqa: BLE001
            error_entry = {'role': 'error', 'message': f'エラー: {e}'}
            self._chat_history.append(error_entry)
            self._broadcast({'type': 'chat', 'entry': error_entry})
        finally:
            self._chat_in_progress = False

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

    def _shutdown(self) -> None:
        """終了処理（別スレッドから呼ばれる）."""
        if self._shutdown_event.is_set():
            return
        self._shutdown_event.set()
        self._running = False
        try:
            self.recorder.stop()
        except Exception:  # noqa: BLE001
            pass

        with self.lock:
            transcripts_copy = list(self.transcripts)

        if transcripts_copy:
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
        self._server = uvicorn.Server(config)

        # SIGINT/SIGTERMで終了処理
        def _signal_handler(_signum, _frame) -> None:
            threading.Thread(target=self._shutdown, daemon=True).start()

        try:
            signal.signal(signal.SIGINT, _signal_handler)
            signal.signal(signal.SIGTERM, _signal_handler)
        except ValueError:
            pass

        print(f'Web UI: http://{self.host}:{self.port}')
        self._server.run()

        if self.output_path:
            print(f'\n出力: {self.output_path}')
