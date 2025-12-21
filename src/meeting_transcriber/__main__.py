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
        choices=['api', 'claude-agent', 'claude-cli', 'auto'],
        help='LLMバックエンド (default: auto)',
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
        '--obsidian-vault',
        type=Path,
        default=None,
        help='Obsidian Vaultのパス',
    )
    parser.add_argument(
        '--obsidian-folder',
        default=None,
        help='Vault内のサブフォルダ',
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

    # その他
    parser.add_argument(
        '--show-config',
        action='store_true',
        help='現在の設定を表示',
    )
    parser.add_argument(
        '--no-tui',
        action='store_true',
        help='TUIを無効化してシンプルモードで実行',
    )

    return parser.parse_args()


def main() -> int:
    """メイン関数."""
    # 環境変数を読み込み
    load_dotenv()

    args = parse_args()

    # デバイス一覧表示
    if args.list_devices:
        list_devices()
        return 0

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
    if args.obsidian_vault:
        merge_kwargs['obsidian_vault'] = args.obsidian_vault.expanduser()
    if args.obsidian_folder:
        merge_kwargs['obsidian_folder'] = args.obsidian_folder
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

    config = config.merge_args(**merge_kwargs)

    try:
        transcriber = MeetingTranscriber(config)
        if args.no_tui:
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
