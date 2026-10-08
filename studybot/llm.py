"""Claude API 呼び出しをまとめたモジュール。"""

from __future__ import annotations

import os
import sys

import anthropic

MODEL = os.environ.get("STUDYBOT_MODEL", "claude-opus-5-5")

# fallbacks="default" は安全分類器が誤って断ったときに別モデルで自動再実行してくれる。
# 対応しているモデルのときだけ付ける。
_FALLBACK_MODELS = {"claude-opus-5-5", "claude-opus-5", "claude-fable-5-1"}


class GenerationError(RuntimeError):
    pass


def generate(system: str, content: list[dict], effort: str = "high", max_tokens: int = 64000) -> str:
    """content（Messages API のコンテンツブロック列）を送り、生成されたテキストを返す。

    生成中のテキストは stderr に流すので進み具合が見える。
    """
    client = anthropic.Anthropic()
    extra = {}
    if MODEL in _FALLBACK_MODELS:
        extra = {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}

    try:
        with client.beta.messages.stream(
            model=MODEL,
            max_tokens=max_tokens,
            system=system,
            output_config={"effort": effort},
            messages=[{"role": "user", "content": content}],
            **extra,
        ) as stream:
            for text in stream.text_stream:
                sys.stderr.write(text)
                sys.stderr.flush()
            message = stream.get_final_message()
    except anthropic.AuthenticationError as e:
        raise GenerationError("APIキーが無効です。ANTHROPIC_API_KEY を確認してください。") from e
    except anthropic.RateLimitError as e:
        raise GenerationError("レート制限に達しました。少し待ってから再実行してください。") from e
    except anthropic.BadRequestError as e:
        raise GenerationError(f"リクエストエラー: {e.message}") from e
    except anthropic.APIStatusError as e:
        raise GenerationError(f"APIエラー ({e.status_code}): {e.message}") from e
    except anthropic.APIConnectionError as e:
        raise GenerationError("ネットワークエラー。接続を確認してください。") from e
    finally:
        sys.stderr.write("\n")

    if message.stop_reason == "refusal":
        raise GenerationError("Claude がこのリクエストへの応答を拒否しました。")
    text = "".join(block.text for block in message.content if block.type == "text")
    if message.stop_reason == "max_tokens":
        text += "\n\n> ⚠️ 出力が長すぎて途中で切れました。資料を分けて再実行してください。\n"
    return text
