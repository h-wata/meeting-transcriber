"""CLIエントリーポイント."""

from __future__ import annotations

import ctypes
import os
import sys


# cuDNNライブラリを事前にロード（他のインポートより先に実行、Linux CUDA環境のみ）
def _preload_cudnn() -> None:
    # Linux以外では不要
    if sys.platform != 'linux':
        return

    try:
        import importlib.util

        spec = importlib.util.find_spec('nvidia.cudnn')
        if spec is None or not spec.submodule_search_locations:
            return

        cudnn_path = list(spec.submodule_search_locations)[0]
        lib_path = os.path.join(cudnn_path, 'lib')

        if not os.path.exists(lib_path):
            return

        # 必要なライブラリを順番にロード
        libs = [
            'libcudnn.so.9',
            'libcudnn_ops.so.9',
            'libcudnn_cnn.so.9',
            'libcudnn_adv.so.9',
            'libcudnn_graph.so.9',
            'libcudnn_engines_precompiled.so.9',
            'libcudnn_engines_runtime_compiled.so.9',
            'libcudnn_heuristic.so.9',
        ]

        for lib in libs:
            lib_file = os.path.join(lib_path, lib)
            if os.path.exists(lib_file):
                try:
                    ctypes.CDLL(lib_file, mode=ctypes.RTLD_GLOBAL)
                except OSError:
                    pass
    except Exception:
        pass


_preload_cudnn()

import argparse  # noqa: E402
from pathlib import Path  # noqa: E402

from dotenv import load_dotenv  # noqa: E402

from meeting_transcriber.audio import AudioRecorder  # noqa: E402
from meeting_transcriber.config import Config  # noqa: E402
from meeting_transcriber.main import MeetingTranscriber  # noqa: E402
from meeting_transcriber.templates import TemplateManager  # noqa: E402


def list_devices() -> None:
    """利用可能な音声デバイスを表示する."""
    devices = AudioRecorder.list_devices()
    print('利用可能な入力デバイス:')
    print('-' * 60)
    for device in devices:
        print(f'  [{device["id"]}] {device["name"]}')
        print(f'       チャンネル: {device["channels"]}, サンプルレート: {device["sample_rate"]}')
    print()


def list_templates(templates_dir: Path) -> None:
    """利用可能なテンプレートを表示する."""
    manager = TemplateManager(templates_dir)
    manager.install_builtin_templates()
    templates = manager.list_templates()

    print('利用可能なテンプレート:')
    print('-' * 60)
    for t in templates:
        print(f'  {t.name:<15} - {t.description}')
    print()


def init_config(force: bool = False) -> int:
    """examples/config.yaml をユーザー設定ディレクトリへコピーする."""
    import shutil

    target = Config.get_default_config_path()
    target.parent.mkdir(parents=True, exist_ok=True)

    if target.exists() and not force:
        print(f'既に存在します: {target}', file=sys.stderr)
        print('上書きする場合は --force を指定してください', file=sys.stderr)
        return 1

    # examples/config.yaml をパッケージから解決
    candidates = [
        Path(__file__).resolve().parent.parent.parent / 'examples' / 'config.yaml',  # 開発インストール
        Path(__file__).resolve().parent / 'examples' / 'config.yaml',  # site-packages 同梱想定
    ]
    source = next((p for p in candidates if p.exists()), None)
    if source is None:
        print('examples/config.yaml が見つかりません（リポジトリ構造を確認してください）', file=sys.stderr)
        return 1

    shutil.copy(source, target)
    print(f'設定ファイルを作成しました: {target}')
    print(f'  雛形: {source}')
    print('編集してから meeting-transcriber を起動してください。')
    return 0


def show_config(config: Config) -> None:
    """現在の設定を表示する."""
    print('現在の設定:')
    print('-' * 60)
    print(f'  設定ファイル: {Config.get_default_config_path()}')
    print(f'  Whisperモデル: {config.model_size}')
    print(f'  言語: {config.language}')
    print(f'  計算デバイス: {config.compute_device}')
    print(f'  バックエンド: {config.backend}')
    print(f'  出力先: {config.get_output_path()}')
    print(f'  テンプレート: {config.template}')
    print(f'  自動更新: {config.auto_update}')
    if config.auto_update:
        print(f'  更新間隔: {config.update_interval}秒')
    print()


def parse_args() -> argparse.Namespace:
    """コマンドライン引数をパースする."""
    parser = argparse.ArgumentParser(
        description='リアルタイム議事録生成ツール',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # Whisper設定
    parser.add_argument(
        '-m',
        '--model',
        choices=['tiny', 'small', 'medium', 'large-v3'],
        help='Whisperモデルサイズ (default: small)',
    )
    parser.add_argument(
        '-l',
        '--language',
        default=None,
        help='認識言語 (default: ja)',
    )
    parser.add_argument(
        '-d',
        '--device',
        type=int,
        default=None,
        help='音声入力デバイスID',
    )
    parser.add_argument(
        '--list-devices',
        action='store_true',
        help='利用可能な音声デバイス一覧を表示',
    )
    parser.add_argument(
        '--no-realtime',
        action='store_true',
        help='リアルタイム文字起こし表示を無効化',
    )
    parser.add_argument(
        '--compute-device',
        choices=['auto', 'cuda', 'cpu'],
        default=None,
        help='Whisper実行デバイス (default: auto)',
    )

    # バックエンド設定
    parser.add_argument(
        '-b',
        '--backend',
        choices=['api', 'claude-agent', 'claude-cli', 'openai_compat', 'local', 'auto'],
        help='LLMバックエンド (default: auto, local は openai_compat の旧名)',
    )

    # 出力設定
    parser.add_argument(
        '-o',
        '--output',
        type=Path,
        default=None,
        help='出力ディレクトリ',
    )
    parser.add_argument(
        '-f',
        '--filename',
        default=None,
        help='出力ファイル名フォーマット',
    )
    parser.add_argument(
        '--simple-output',
        type=Path,
        default=None,
        help='シンプル出力モード（単一ファイルを直接出力）',
    )
    parser.add_argument(
        '--open-after',
        action='store_true',
        help='終了後にファイルを開く',
    )

    # テンプレート設定
    parser.add_argument(
        '-t',
        '--template',
        default=None,
        help='使用するテンプレート名',
    )
    parser.add_argument(
        '--list-templates',
        action='store_true',
        help='利用可能なテンプレート一覧を表示',
    )

    # 更新設定
    parser.add_argument(
        '--auto-update',
        action='store_true',
        help='自動更新モードを有効化',
    )
    parser.add_argument(
        '--update-interval',
        type=int,
        default=None,
        help='自動更新の間隔（秒）',
    )
    parser.add_argument(
        '--version-history',
        action='store_true',
        help='更新ごとにバージョン保存',
    )
    parser.add_argument(
        '--transcript-only',
        action='store_true',
        help='文字起こしのみ（議事録を生成しない）',
    )

    # バッチ処理
    parser.add_argument(
        '--from-file',
        type=Path,
        default=None,
        help='既存の文字起こしファイルから議事録を生成（globパターン可）',
    )
    parser.add_argument(
        '-i',
        '--input',
        type=Path,
        default=None,
        help='音声/動画ファイルから文字起こし→議事録生成（wav/mp3/mp4/mov等、globパターン可、要ffmpeg）',
    )

    # その他
    parser.add_argument(
        '--show-config',
        action='store_true',
        help='現在の設定を表示',
    )
    parser.add_argument(
        '--init-config',
        action='store_true',
        help='examples/config.yaml をユーザー設定ディレクトリにコピーする',
    )
    parser.add_argument(
        '--force',
        action='store_true',
        help='--init-config 時に既存のconfig.yamlを上書きする',
    )
    parser.add_argument(
        '--no-tui',
        action='store_true',
        help='TUIを無効化してシンプルモードで実行',
    )
    parser.add_argument(
        '--web',
        action='store_true',
        help='Web UIモードで実行（ブラウザで議事録を表示）',
    )
    parser.add_argument(
        '--web-host',
        default='127.0.0.1',
        help='Web UIのバインドホスト (default: 127.0.0.1)',
    )
    parser.add_argument(
        '--web-port',
        type=int,
        default=8765,
        help='Web UIのポート (default: 8765)',
    )
    parser.add_argument(
        '--no-browser',
        action='store_true',
        help='Web UIモードでブラウザを自動起動しない',
    )

    return parser.parse_args()


def parse_transcript_file(path: Path) -> list:
    """transcript_raw.txtをTranscriptEntryリストにパースする."""
    from meeting_transcriber.config import TranscriptEntry

    entries = []
    text = path.read_text(encoding='utf-8')
    import re

    # [HH:MM:SS] テキスト の形式をパース
    pattern = re.compile(r'^\[(\d{2}:\d{2}:\d{2})\]\s*(.+)$', re.MULTILINE)
    for i, match in enumerate(pattern.finditer(text)):
        time_str, content = match.group(1), match.group(2)
        from datetime import datetime

        timestamp = datetime.strptime(time_str, '%H:%M:%S')
        entries.append(TranscriptEntry(timestamp=timestamp, text=content, index=i))

    # パターンにマッチしない場合はテキスト全体を1エントリとして扱う
    if not entries:
        from datetime import datetime

        entries.append(TranscriptEntry(timestamp=datetime.now(), text=text.strip(), index=0))

    return entries


_AUDIO_EXTENSIONS = {'.wav', '.mp3', '.flac', '.m4a', '.ogg', '.opus', '.aac', '.wma'}
_VIDEO_EXTENSIONS = {'.mp4', '.mov', '.mkv', '.webm', '.avi', '.flv', '.wmv', '.m4v'}
_MEDIA_EXTENSIONS = _AUDIO_EXTENSIONS | _VIDEO_EXTENSIONS


def _check_ffmpeg_available() -> bool:
    """Check that ffmpeg is on PATH."""
    import subprocess

    try:
        result = subprocess.run(['ffmpeg', '-version'], capture_output=True, timeout=5, check=False)
        return result.returncode == 0
    except (FileNotFoundError, subprocess.SubprocessError):
        return False


def run_from_audio(args: argparse.Namespace, config: Config) -> int:
    """音声/動画ファイルから文字起こし → 議事録生成する."""
    import glob as glob_module
    from datetime import datetime, timedelta

    from meeting_transcriber.backends.factory import get_backend
    from meeting_transcriber.config import TranscriptEntry
    from meeting_transcriber.minutes import MinutesGenerator, MinutesUpdater
    from meeting_transcriber.transcriber import Transcriber

    # CLI 引数を config にマージ
    merge_kwargs = {}
    if args.backend:
        merge_kwargs['backend'] = args.backend
    if args.template:
        merge_kwargs['template'] = args.template
    if args.model:
        merge_kwargs['model_size'] = args.model
    if args.language:
        merge_kwargs['language'] = args.language
    if args.compute_device:
        merge_kwargs['compute_device'] = args.compute_device
    if args.output:
        merge_kwargs['output_dir'] = args.output.expanduser()
    if args.simple_output:
        merge_kwargs['simple_output_dir'] = args.simple_output.expanduser()
    if args.transcript_only:
        merge_kwargs['transcript_only'] = True
    config = config.merge_args(**merge_kwargs)

    # ファイル展開
    input_path = args.input.expanduser()
    if '*' in str(input_path) or '?' in str(input_path):
        files = sorted(Path(p) for p in glob_module.glob(str(input_path)))
    elif input_path.is_dir():
        files = sorted(p for p in input_path.iterdir() if p.suffix.lower() in _MEDIA_EXTENSIONS)
    else:
        files = [input_path]

    if not files:
        print(f'ファイルが見つかりません: {input_path}', file=sys.stderr)
        return 1

    # 拡張子チェック（警告のみ、未知の拡張子は ffmpeg に任せる）
    for f in files:
        if f.suffix.lower() not in _MEDIA_EXTENSIONS:
            print(f'警告: 未知の拡張子 {f.suffix} ({f.name})。ffmpeg でデコードを試みます', file=sys.stderr)

    # ffmpeg 確認
    if not _check_ffmpeg_available():
        print(
            'エラー: ffmpeg が見つかりません。音声/動画ファイル入力には ffmpeg が必要です。\n'
            '  Ubuntu/Debian: sudo apt install ffmpeg\n'
            '  macOS: brew install ffmpeg',
            file=sys.stderr,
        )
        return 1

    print(f'{len(files)} 件のメディアファイルを処理します')

    # Whisper / Backend / Template 初期化
    transcriber = Transcriber(
        model_size=config.model_size,
        language=config.language,
        device=config.compute_device,
    )

    backend = None if config.transcript_only else get_backend(config)
    template_manager = TemplateManager(config.templates_dir)
    template_manager.install_builtin_templates()
    template = template_manager.get_template(config.template)
    if template is None and not config.transcript_only:
        print(f'エラー: テンプレートが見つかりません: {config.template}', file=sys.stderr)
        return 1
    generator = None if config.transcript_only else MinutesGenerator(backend, template_manager)

    output_root = config.get_output_path()
    output_root.mkdir(parents=True, exist_ok=True)

    overall_ok = True
    for i, media_path in enumerate(files, 1):
        print(f'\n[{i}/{len(files)}] {media_path}')
        try:
            # ファイル毎にセッションディレクトリを作る (simple モードでない場合)
            file_stem = media_path.stem
            start_time = datetime.now()
            session_name = f'{file_stem}_{start_time.strftime("%Y%m%d_%H%M%S")}'

            # 文字起こし: segment ごとの (start, end, text) → TranscriptEntry
            entries: list[TranscriptEntry] = []
            last_pct = -1
            for idx, (start_sec, _end_sec, text) in enumerate(transcriber.transcribe_file(media_path)):
                entry = TranscriptEntry(
                    timestamp=start_time + timedelta(seconds=start_sec),
                    text=text,
                    index=idx,
                )
                entries.append(entry)
                # 簡易進捗表示（10% 刻み）
                if idx % 20 == 0:
                    print(f'  ...{idx} segments transcribed (t={start_sec:.0f}s)')
                last_pct = idx

            if not entries:
                print('  スキップ（無音または認識結果が空）')
                continue

            print(f'  {len(entries)} segments を取得')

            # Updater で出力構造を統一
            updater = MinutesUpdater(
                generator=generator,
                output_dir=output_root,
                template=template,
                start_time=start_time,
                filename_format=session_name,  # ファイル名から固有のセッション名
                version_history=False,
                simple_mode=config.simple_output_dir is not None,
            )

            if config.transcript_only:
                save_path = updater.save_transcript_only(entries)
                print(f'  完了 → {save_path}')
                continue

            # 議事録生成
            result = updater.update(entries, full=True)
            if not result.success:
                print(f'  議事録生成失敗: {result.error}', file=sys.stderr)
                overall_ok = False
                continue

            save_path = updater.save(entries)
            print(f'  完了 → {save_path}')

        except Exception as e:  # noqa: BLE001
            print(f'  エラー: {e}', file=sys.stderr)
            overall_ok = False

        _ = last_pct  # silence linter

    print(f'\n全 {len(files)} 件の処理が完了しました')
    return 0 if overall_ok else 2


def run_batch(args: argparse.Namespace, config: Config) -> int:
    """既存の文字起こしファイルから議事録をバッチ生成する."""
    import glob as glob_module

    from meeting_transcriber.backends.factory import get_backend
    from meeting_transcriber.minutes import MinutesGenerator

    # backendの上書き
    if args.backend:
        config = config.merge_args(backend=args.backend)
    if args.template:
        config = config.merge_args(template=args.template)

    # globパターン展開
    input_path = args.from_file.expanduser()
    if '*' in str(input_path) or '?' in str(input_path):
        files = sorted(Path(p) for p in glob_module.glob(str(input_path)))
    elif input_path.is_dir():
        files = sorted(input_path.glob('**/transcript_raw.txt'))
    else:
        files = [input_path]

    if not files:
        print(f'ファイルが見つかりません: {input_path}', file=sys.stderr)
        return 1

    print(f'{len(files)} 件のファイルを処理します')

    # バックエンドとテンプレートの初期化
    backend = get_backend(config)
    template_manager = TemplateManager(config.templates_dir)
    template_manager.install_builtin_templates()
    template = template_manager.get_template(config.template)
    generator = MinutesGenerator(backend, template_manager)

    for i, file_path in enumerate(files, 1):
        print(f'\n[{i}/{len(files)}] {file_path}')

        # 既に議事録がある場合はスキップ
        output_path = file_path.parent / 'minutes.md'
        if output_path.exists():
            print('  スキップ（議事録が既に存在します）')
            continue

        try:
            entries = parse_transcript_file(file_path)
            if not entries:
                print('  スキップ（空のファイル）')
                continue

            print(f'  {len(entries)} 件のエントリを処理中...')
            context = TemplateManager.get_default_context(
                entries[0].timestamp,
                entries[-1].timestamp,
                1,
            )
            minutes = generator.generate_full(entries, template, context)

            output_path.write_text(minutes, encoding='utf-8')
            final_path = file_path.parent / 'minutes_final.md'
            final_path.write_text(minutes, encoding='utf-8')
            print(f'  完了 → {output_path}')

        except Exception as e:
            print(f'  エラー: {e}', file=sys.stderr)

    print(f'\n全{len(files)}件の処理が完了しました')
    return 0


def main() -> int:
    """メイン関数."""
    # 環境変数を読み込み
    load_dotenv()

    args = parse_args()

    # デバイス一覧表示
    if args.list_devices:
        list_devices()
        return 0

    # 設定ファイル雛形生成
    if args.init_config:
        return init_config(force=args.force)

    # 設定を読み込み
    config = Config.load_default()

    # テンプレート一覧表示
    if args.list_templates:
        list_templates(config.templates_dir)
        return 0

    # 設定表示
    if args.show_config:
        show_config(config)
        return 0

    # バッチ処理モード
    if args.from_file:
        return run_batch(args, config)

    # 音声/動画ファイル入力モード
    if args.input:
        return run_from_audio(args, config)

    # コマンドライン引数をマージ
    merge_kwargs = {}
    if args.model:
        merge_kwargs['model_size'] = args.model
    if args.language:
        merge_kwargs['language'] = args.language
    if args.device is not None:
        merge_kwargs['device_id'] = args.device
    if args.no_realtime:
        merge_kwargs['realtime_display'] = False
    if args.compute_device:
        merge_kwargs['compute_device'] = args.compute_device
    if args.backend:
        merge_kwargs['backend'] = args.backend
    if args.output:
        merge_kwargs['output_dir'] = args.output.expanduser()
    if args.filename:
        merge_kwargs['filename_format'] = args.filename
    if args.simple_output:
        merge_kwargs['simple_output_dir'] = args.simple_output.expanduser()
    if args.open_after:
        merge_kwargs['open_after'] = True
    if args.template:
        merge_kwargs['template'] = args.template
    if args.auto_update:
        merge_kwargs['auto_update'] = True
    if args.update_interval:
        merge_kwargs['update_interval'] = args.update_interval
    if args.version_history:
        merge_kwargs['version_history'] = True
    if args.transcript_only:
        merge_kwargs['transcript_only'] = True

    config = config.merge_args(**merge_kwargs)

    try:
        transcriber = MeetingTranscriber(config)
        if args.web:
            transcriber.run_web(
                host=args.web_host,
                port=args.web_port,
                open_browser=not args.no_browser,
            )
        elif args.no_tui:
            transcriber.run()
        else:
            transcriber.run_tui()
        return 0
    except KeyboardInterrupt:
        return 0
    except Exception as e:
        print(f'エラー: {e}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
