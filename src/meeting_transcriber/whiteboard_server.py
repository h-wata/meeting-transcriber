"""ホワイトボード用WebSocketサーバー."""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from pathlib import Path
from typing import TYPE_CHECKING

from aiohttp import web

if TYPE_CHECKING:
    from meeting_transcriber.backends.base import Backend
    from meeting_transcriber.config import TranscriptEntry

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / 'static'


class WhiteboardServer:
    """ホワイトボードWebSocket + HTTPサーバー."""

    def __init__(
        self,
        backend: Backend,
        host: str = '0.0.0.0',
        port: int = 8765,
    ) -> None:
        self.host = host
        self.port = port
        self._clients: set[web.WebSocketResponse] = set()
        self._lock = asyncio.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._runner: web.AppRunner | None = None

        # ホワイトボードエンジン
        from meeting_transcriber.whiteboard import WhiteboardEngine

        self.engine = WhiteboardEngine(backend)

    def start(self) -> None:
        """バックグラウンドスレッドでサーバーを起動."""
        self._thread = threading.Thread(target=self._run_server, daemon=True)
        self._thread.start()

    def _run_server(self) -> None:
        """サーバーを実行（別スレッド）."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._start_app())

    async def _start_app(self) -> None:
        """aiohttp アプリケーションを起動."""
        app = web.Application()
        app.router.add_get('/ws', self._handle_websocket)
        app.router.add_get('/', self._handle_index)
        app.router.add_static('/static/', STATIC_DIR, name='static')

        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self.host, self.port)
        await site.start()

        logger.info('Whiteboard server started on http://%s:%s', self.host, self.port)

        # サーバーを維持
        try:
            while True:
                await asyncio.sleep(3600)
        except asyncio.CancelledError:
            pass

    async def _handle_index(self, _request: web.Request) -> web.Response:
        """インデックスページを返す."""
        index_path = STATIC_DIR / 'whiteboard.html'
        if index_path.exists():
            content = index_path.read_text(encoding='utf-8')
            return web.Response(text=content, content_type='text/html')
        return web.Response(text='Whiteboard UI not found', status=404)

    async def _handle_websocket(self, request: web.Request) -> web.WebSocketResponse:
        """WebSocket接続を処理."""
        ws = web.WebSocketResponse()
        await ws.prepare(request)

        async with self._lock:
            self._clients.add(ws)
            client_count = len(self._clients)

        logger.info('Client connected (total: %d)', client_count)

        # 現在の状態を新しいクライアントに送信
        state = self.engine.state.to_dict()
        await ws.send_json({
            'type': 'state',
            'data': state,
            'clients': client_count,
        })

        # クライアント数を全員に通知
        await self._broadcast({
            'type': 'clients',
            'count': client_count,
        })

        try:
            async for msg in ws:
                if msg.type == web.WSMsgType.TEXT:
                    await self._handle_message(ws, msg.data)
                elif msg.type == web.WSMsgType.ERROR:
                    logger.error('WebSocket error: %s', ws.exception())
        finally:
            async with self._lock:
                self._clients.discard(ws)
                client_count = len(self._clients)

            logger.info('Client disconnected (total: %d)', client_count)

            await self._broadcast({
                'type': 'clients',
                'count': client_count,
            })

        return ws

    async def _handle_message(self, ws: web.WebSocketResponse, raw: str) -> None:
        """クライアントからのメッセージを処理."""
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return

        msg_type = data.get('type', '')

        if msg_type == 'request_state':
            # 状態をリクエスト
            state = self.engine.state.to_dict()
            await ws.send_json({
                'type': 'state',
                'data': state,
                'clients': len(self._clients),
            })

        elif msg_type == 'cursor':
            # カーソル位置をブロードキャスト（送信元以外）
            await self._broadcast(data, exclude=ws)

        elif msg_type == 'reaction':
            # リアクション（いいね等）をブロードキャスト
            await self._broadcast(data)

    async def _broadcast(
        self,
        data: dict,
        exclude: web.WebSocketResponse | None = None,
    ) -> None:
        """全クライアントにメッセージを送信."""
        async with self._lock:
            clients = set(self._clients)

        for client in clients:
            if client is exclude or client.closed:
                continue
            try:
                await client.send_json(data)
            except (ConnectionResetError, RuntimeError):
                pass

    def update_whiteboard(
        self,
        transcripts: list[TranscriptEntry],
        full: bool = False,
    ) -> None:
        """ホワイトボードを更新（メインスレッドから呼ばれる）."""
        if not transcripts:
            return

        def _do_update() -> None:
            try:
                if full:
                    self.engine.generate(transcripts)
                else:
                    self.engine.update(transcripts)

                # 結果をブロードキャスト
                state = self.engine.state.to_dict()
                if self._loop and self._loop.is_running():
                    asyncio.run_coroutine_threadsafe(
                        self._broadcast({
                            'type': 'state',
                            'data': state,
                            'clients': len(self._clients),
                        }),
                        self._loop,
                    )
            except Exception:
                logger.exception('Whiteboard update failed')

        # 別スレッドで実行（LLM呼び出しはブロッキング）
        thread = threading.Thread(target=_do_update, daemon=True)
        thread.start()

    def send_transcript(self, text: str) -> None:
        """文字起こしテキストをリアルタイムで送信."""
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(
                self._broadcast({
                    'type': 'transcript',
                    'text': text,
                }),
                self._loop,
            )

    def stop(self) -> None:
        """サーバーを停止."""
        if self._loop and self._runner:
            asyncio.run_coroutine_threadsafe(
                self._runner.cleanup(),
                self._loop,
            )
