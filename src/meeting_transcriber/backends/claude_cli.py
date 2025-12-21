"""Claude Code CLIバックエンド."""

from __future__ import annotations

import os
import subprocess

from meeting_transcriber.backends.base import Backend


class ClaudeCLIBackend(Backend):
    """Claude Code CLIをsubprocessで呼び出し（Maxプラン活用）."""

    def generate(self, prompt: str) -> str:
        """プロンプトから議事録を生成する."""
        # ANTHROPIC_API_KEY があるとAPI課金になるので一時的に除去
        env = os.environ.copy()
        env.pop('ANTHROPIC_API_KEY', None)

        result = subprocess.run(
            ['claude', '-p', prompt, '--output-format', 'text'],
            capture_output=True,
            text=True,
            timeout=120,
            env=env,
            check=False,
        )

        if result.returncode != 0:
            raise RuntimeError(f'Claude CLI error: {result.stderr}')

        return result.stdout.strip()

    @staticmethod
    def check_available() -> bool:
        """Claude CLIが利用可能か確認する."""
        try:
            result = subprocess.run(
                ['claude', '--version'],
                capture_output=True,
                timeout=5,
                check=False,
            )
            return result.returncode == 0
        except FileNotFoundError:
            return False
