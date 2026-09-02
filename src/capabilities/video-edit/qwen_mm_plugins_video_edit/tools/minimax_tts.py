"""MCP tool: synchronous text-to-speech via MiniMax."""

from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from shared.content import text_error
from shared.env import get_env
from shared.retry import retry_call

MiniMaxModel = Literal[
    "speech-2.8-hd",
    "speech-2.8-turbo",
    "speech-2.6-hd",
    "speech-2.6-turbo",
    "speech-02-hd",
    "speech-02-turbo",
    "speech-01-hd",
    "speech-01-turbo",
]
MiniMaxRegion = Literal["global_en", "cn_zh"]
AudioFormat = Literal["mp3", "wav", "flac", "pcm"]


class MiniMaxVoiceSetting(BaseModel):
    voice_id: str = Field(description="System, cloned, or generated voice ID.")
    speed: float = Field(
        default=1.0, ge=0.5, le=2.0, description="Speech speed from 0.5 to 2.0."
    )
    vol: float = Field(
        default=1.0, gt=0, le=10.0, description="Speech volume above 0 and up to 10."
    )
    pitch: int = Field(
        default=0, ge=-12, le=12, description="Pitch adjustment from -12 to 12."
    )
    emotion: (
        Literal[
            "happy",
            "sad",
            "angry",
            "fearful",
            "disgusted",
            "surprised",
            "calm",
            "fluent",
            "whisper",
        ]
        | None
    ) = Field(
        default=None, description="Optional emotion supported by the selected model."
    )


class MiniMaxAudioSetting(BaseModel):
    sample_rate: Literal[8000, 16000, 22050, 24000, 32000, 44100] = Field(
        default=32000,
        description="Audio sample rate in Hz.",
    )
    bitrate: Literal[32000, 64000, 128000, 256000] = Field(
        default=128000,
        description="MP3 bitrate in bits per second.",
    )
    format: AudioFormat = Field(default="mp3", description="Generated audio format.")
    channel: Literal[1, 2] = Field(
        default=1, description="One channel for mono or two for stereo."
    )


class MiniMaxVoiceModify(BaseModel):
    pitch: int | None = Field(default=None, ge=-100, le=100)
    intensity: int | None = Field(default=None, ge=-100, le=100)
    timbre: int | None = Field(default=None, ge=-100, le=100)
    sound_effects: (
        Literal["spacious_echo", "auditorium_echo", "lofi_telephone", "robotic"] | None
    ) = None


class MiniMaxTtsArgs(BaseModel):
    text: str = Field(
        description="Text to synthesize, up to 10,000 characters.",
        min_length=1,
        max_length=9999,
    )
    model: MiniMaxModel = Field(
        default="speech-2.8-hd", description="Speech synthesis model."
    )
    region: MiniMaxRegion = Field(
        default="global_en",
        description="API region: global_en for the global endpoint or cn_zh for the China endpoint.",
    )
    voice_setting: MiniMaxVoiceSetting = Field(
        description="Voice ID and optional voice controls."
    )
    audio_setting: MiniMaxAudioSetting = Field(
        default_factory=MiniMaxAudioSetting,
        description="Output sample rate, bitrate, format, and channel count.",
    )
    language_boost: str | None = Field(
        default=None,
        description="Optional language or dialect boost; use 'auto' for automatic detection.",
    )
    pronunciation_dict: dict[str, list[str]] | None = Field(
        default=None,
        description="Optional pronunciation replacements, such as a tone list.",
    )
    voice_modify: MiniMaxVoiceModify | None = Field(
        default=None, description="Optional voice effects."
    )
    subtitle_enable: bool = Field(
        default=False, description="Whether to generate aligned subtitles."
    )
    stream: Literal[False] = Field(
        default=False, description="This synchronous tool uses non-streaming responses."
    )
    output_format: Literal["hex", "url"] = Field(
        default="hex",
        description="Return hexadecimal audio for local saving or a temporary URL.",
    )
    output_dir: str | None = Field(
        default=None,
        description="Directory for decoded audio. Defaults to a temporary qwen-mm-plugins directory.",
    )


TOOL: dict[str, Any] = {
    "name": "minimax_tts",
    "description": (
        "Synchronous text-to-speech using MiniMax speech models. "
        "Supports global and China endpoints, configurable voices, language boosting, "
        "and MP3, WAV, FLAC, or PCM output. Hexadecimal responses are decoded to a local audio file."
    ),
    "args": MiniMaxTtsArgs,
}


_ENDPOINTS = {
    "global_en": "https://api.minimax.io/v1/t2a_v2",
    "cn_zh": "https://api.minimaxi.com/v1/t2a_v2",
}
_DEFAULT_AUDIO_SETTING = {
    "sample_rate": 32000,
    "bitrate": 128000,
    "format": "mp3",
    "channel": 1,
}


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, BaseModel):
        return value.model_dump(exclude_none=True)
    return {key: item for key, item in dict(value or {}).items() if item is not None}


def _retryable(error: Exception) -> bool:
    status = getattr(getattr(error, "response", None), "status_code", None)
    if isinstance(status, int):
        return status in (408, 429) or status >= 500
    return True


def _request(endpoint: str, api_key: str, payload: dict[str, Any]) -> dict[str, Any]:
    import requests

    def post() -> dict[str, Any]:
        response = requests.post(
            endpoint,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=60,
        )
        response.raise_for_status()
        result = response.json()
        if not isinstance(result, dict):
            raise TypeError("response is not a JSON object")
        return result

    result = retry_call(
        post, attempts=3, base_backoff=1.0, mode="exp", should_retry=_retryable
    )
    if not isinstance(result, dict):
        raise TypeError("response is not a JSON object")
    return result


def handle(arguments: dict[str, Any]) -> list[dict[str, Any]]:
    api_key = get_env("MINIMAX_API_KEY")
    if not api_key:
        return text_error("MINIMAX_API_KEY not set")

    text = arguments.get("text")
    if not isinstance(text, str) or not text.strip():
        return text_error("text is required")
    if len(text) >= 10000:
        return text_error("text must be shorter than 10,000 characters")

    region = arguments.get("region", "global_en")
    endpoint = _ENDPOINTS.get(region)
    if endpoint is None:
        return text_error("region must be global_en or cn_zh")

    voice_setting = _as_dict(arguments.get("voice_setting"))
    if not voice_setting.get("voice_id"):
        return text_error("voice_setting.voice_id is required")

    audio_setting = {
        **_DEFAULT_AUDIO_SETTING,
        **_as_dict(arguments.get("audio_setting")),
    }
    audio_format = audio_setting.get("format")
    if audio_format not in ("mp3", "wav", "flac", "pcm"):
        return text_error("audio_setting.format must be mp3, wav, flac, or pcm")

    output_format = arguments.get("output_format", "hex")
    if output_format not in ("hex", "url"):
        return text_error("output_format must be hex or url")
    if arguments.get("stream", False):
        return text_error("streaming is not supported by this tool")

    payload: dict[str, Any] = {
        "model": arguments.get("model", "speech-2.8-hd"),
        "text": text,
        "stream": False,
        "output_format": output_format,
        "voice_setting": voice_setting,
        "audio_setting": audio_setting,
        "subtitle_enable": bool(arguments.get("subtitle_enable", False)),
    }
    for field in ("language_boost", "pronunciation_dict", "voice_modify"):
        value = arguments.get(field)
        if value is not None:
            payload[field] = _as_dict(value) if field != "language_boost" else value

    try:
        import requests
    except ImportError:
        return text_error("missing dependency. Install with: pip install requests")

    try:
        result = _request(endpoint, api_key, payload)
    except requests.RequestException as error:
        status = getattr(getattr(error, "response", None), "status_code", None)
        detail = f" (HTTP {status})" if isinstance(status, int) else ""
        return text_error(f"request failed{detail}: {type(error).__name__}")
    except (TypeError, ValueError) as error:
        return text_error(f"request failed: {type(error).__name__}")

    base_resp = result.get("base_resp") or {}
    status_code = base_resp.get("status_code")
    if status_code not in (None, 0):
        return text_error(
            f"[{status_code}] {base_resp.get('status_msg', 'request failed')}"
        )

    data = result.get("data")
    if not isinstance(data, dict):
        return text_error("response did not include audio data")
    if data.get("status") != 2:
        return text_error(
            f"audio synthesis did not complete (status: {data.get('status')})"
        )
    audio = data.get("audio")
    if not isinstance(audio, str) or not audio:
        return text_error("response did not include audio content")

    lines = [
        f"**Model**: {payload['model']}",
        f"**Region**: {region}",
        f"**Audio format**: {audio_format}",
    ]
    if output_format == "url":
        lines.insert(0, f"**Audio URL**: {audio}")
        return [{"type": "text", "text": "\n".join(lines)}]

    try:
        audio_bytes = bytes.fromhex(audio)
    except ValueError:
        return text_error("response audio was not valid hexadecimal data")
    if not audio_bytes:
        return text_error("response audio was empty")

    output_dir = arguments.get("output_dir")
    destination = (
        Path(output_dir).expanduser().resolve()
        if output_dir
        else Path(tempfile.gettempdir()).resolve() / "qwen-mm-plugins"
    )
    cache_key = hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()[:16]
    audio_file = destination / f"minimax_tts_{cache_key}.{audio_format}"
    try:
        destination.mkdir(parents=True, exist_ok=True)
        audio_file.write_bytes(audio_bytes)
    except OSError as error:
        return text_error(f"failed to save audio: {error}")

    lines.insert(0, f"**Saved to**: {audio_file}")
    extra_info = result.get("extra_info") or {}
    if extra_info.get("audio_length") is not None:
        lines.append(f"**Duration (ms)**: {extra_info['audio_length']}")
    if extra_info.get("usage_characters") is not None:
        lines.append(f"**Characters**: {extra_info['usage_characters']}")
    return [{"type": "text", "text": "\n".join(lines)}]
