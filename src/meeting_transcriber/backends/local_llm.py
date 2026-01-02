"""ローカルLLMバックエンド（airllm使用）."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from meeting_transcriber.backends.base import Backend

if TYPE_CHECKING:
    from airllm import AutoModel


@dataclass
class LocalLLMConfig:
    """ローカルLLM設定."""

    model_name: str = 'Qwen/Qwen2.5-32B-Instruct'
    compression: str | None = '4bit'  # 4bit, 8bit, None
    max_new_tokens: int = 4096
    cache_dir: Path | None = None  # モデルキャッシュディレクトリ

    @classmethod
    def from_dict(cls, data: dict) -> LocalLLMConfig:
        """辞書からLocalLLMConfigを作成."""
        config = cls()
        if 'model_name' in data:
            config.model_name = data['model_name']
        if 'compression' in data:
            config.compression = data['compression']
        if 'max_new_tokens' in data:
            config.max_new_tokens = data['max_new_tokens']
        if 'cache_dir' in data and data['cache_dir']:
            config.cache_dir = Path(data['cache_dir']).expanduser()
        return config


class LocalLLMBackend(Backend):
    """ローカルLLMバックエンド（airllm + Qwen）.

    省VRAMで大規模モデルを実行可能。
    4GB VRAMで70Bモデル、8GB VRAMで405Bモデルを動作可能。
    """

    def __init__(self, config: LocalLLMConfig | None = None) -> None:
        self.config = config or LocalLLMConfig()
        self._model: AutoModel | None = None

    def _get_model(self) -> AutoModel:
        """モデルを遅延ロード."""
        if self._model is None:
            from airllm import AutoModel

            print(f'ローカルLLMをロード中: {self.config.model_name}')
            if self.config.compression:
                print(f'  圧縮: {self.config.compression}')

            kwargs = {}
            if self.config.compression:
                kwargs['compression'] = self.config.compression
            if self.config.cache_dir:
                kwargs['layer_shards_saving_path'] = str(self.config.cache_dir)

            # HuggingFaceトークンがあれば使用
            hf_token = os.environ.get('HF_TOKEN') or os.environ.get('HUGGING_FACE_HUB_TOKEN')
            if hf_token:
                kwargs['hf_token'] = hf_token

            self._model = AutoModel.from_pretrained(
                self.config.model_name,
                **kwargs,
            )
            print('モデルのロード完了')

        return self._model

    def generate(self, prompt: str) -> str:
        """プロンプトからテキストを生成する."""
        model = self._get_model()

        # チャット形式のプロンプトを構築
        chat_prompt = self._build_chat_prompt(prompt)

        # トークナイズ
        input_tokens = model.tokenizer(
            chat_prompt,
            return_tensors='pt',
            truncation=True,
            max_length=32768,  # Qwen2.5は128Kまで対応だが、入力は制限
        )

        # 生成
        generation_output = model.generate(
            input_tokens['input_ids'].cuda(),
            max_new_tokens=self.config.max_new_tokens,
            do_sample=True,
            temperature=0.7,
            top_p=0.9,
            use_cache=True,
            return_dict_in_generate=True,
        )

        # デコード
        output = model.tokenizer.decode(
            generation_output.sequences[0],
            skip_special_tokens=True,
        )

        # プロンプト部分を除去してレスポンスのみ返す
        response = self._extract_response(output, chat_prompt)
        return response

    def _build_chat_prompt(self, prompt: str) -> str:
        """Qwen形式のチャットプロンプトを構築."""
        # Qwen2.5のチャットテンプレート
        return f"""<|im_start|>system
あなたは優秀な議事録作成アシスタントです。会議の文字起こしから構造化された議事録を作成します。
<|im_end|>
<|im_start|>user
{prompt}
<|im_end|>
<|im_start|>assistant
"""

    def _extract_response(self, full_output: str, prompt: str) -> str:
        """生成結果からレスポンス部分のみを抽出."""
        # assistant以降の部分を抽出
        if '<|im_start|>assistant' in full_output:
            response = full_output.split('<|im_start|>assistant')[-1]
            # 終了トークンがあれば除去
            if '<|im_end|>' in response:
                response = response.split('<|im_end|>')[0]
            return response.strip()

        # フォールバック: プロンプトを除去
        if prompt in full_output:
            return full_output.replace(prompt, '').strip()

        return full_output.strip()

    @staticmethod
    def check_available() -> bool:
        """airllmが利用可能か確認する."""
        try:
            import airllm  # noqa: F401
            return True
        except ImportError:
            return False

    @staticmethod
    def check_gpu_available() -> bool:
        """GPUが利用可能か確認する."""
        try:
            import torch
            return torch.cuda.is_available()
        except ImportError:
            return False
