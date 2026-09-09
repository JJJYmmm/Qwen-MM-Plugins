"""Offline MiniMax contract, failure handling, and HTTP download integration tests."""

import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
import requests
from pydantic import ValidationError

import mcp_framework
import qwen_mm_plugins_video_edit as ve
from qwen_mm_plugins_video_edit.tools import minimax_tts
from shared import api_dashscope, retry


def completed(audio="https://example.com/audio.mp3", **data):
    return {
        "base_resp": {"status_code": 0},
        "data": {"status": 2, "audio": audio, **data},
        "extra_info": {"audio_length": 1500, "usage_characters": 5},
    }


def call(**kwargs):
    spec = next(spec for spec in ve.SPECS if spec.name == "minimax_tts")
    blocks = asyncio.run(mcp_framework._make_wrapper(spec)(text="Hello", voice="narrator", **kwargs))
    assert len(blocks) == 1 and blocks[0].type == "text"
    return blocks[0].text


@pytest.fixture(autouse=True)
def isolated_config(monkeypatch):
    monkeypatch.setattr(minimax_tts, "get_env", lambda name: "test-token" if name == "MINIMAX_API_KEY" else None)
    monkeypatch.setattr(retry.time, "sleep", lambda seconds: None)


@pytest.fixture
def request_stub(monkeypatch):
    calls = []

    def request(endpoint, api_key, payload):
        calls.append((endpoint, api_key, payload))
        return completed(subtitle_file="https://example.com/subtitles.json")

    monkeypatch.setattr(minimax_tts, "_request", request)
    return calls


def test_public_schema_keeps_advanced_settings_optional_with_defaults():
    schema = next(tool for tool in ve.list_tools() if tool["name"] == "minimax_tts")["inputSchema"]
    assert set(schema["properties"]) == {
        "text",
        "voice",
        "language_type",
        "output_dir",
        "model",
        "region",
        "subtitle_enable",
        "voice_setting",
        "audio_setting",
        "pronunciation_dict",
        "voice_modify",
        "stream",
        "output_format",
    }
    assert set(schema["required"]) == {"text", "voice"}
    assert schema["additionalProperties"] is False
    assert schema["properties"]["voice_setting"]["default"]["speed"] == 1.0
    assert schema["properties"]["audio_setting"]["default"]["format"] == "mp3"
    assert schema["properties"]["output_format"]["default"] == "url"
    assert schema["properties"]["stream"]["default"] is False
    assert schema["properties"]["region"]["default"] == "global"


@pytest.mark.parametrize(
    "changes",
    [
        {"text": " "},
        {"text": "x" * 10000},
        {"voice": "\n"},
        {"region": "global_en"},
        {"language_type": ""},
        {"stream": True},
        {"output_format": "base64"},
        {"voice_setting": {"voice_id": "narrator"}},
        {"voice_setting": {"speed": 3}},
        {"voice_setting": {"vol": 0}},
        {"audio_setting": {"format": "aac"}},
        {"voice_modify": {"timbre": 101}},
    ],
)
def test_invalid_input_is_rejected_before_provider_call(changes, request_stub):
    spec = next(spec for spec in ve.SPECS if spec.name == "minimax_tts")
    with pytest.raises(ValidationError):
        asyncio.run(mcp_framework._make_wrapper(spec)(**{"text": "Hello", "voice": "narrator", **changes}))
    assert request_stub == []


def test_missing_key_does_not_call_provider(monkeypatch, request_stub):
    monkeypatch.setattr(minimax_tts, "get_env", lambda name: None)
    assert call() == "Error: MINIMAX_API_KEY not set"
    assert request_stub == []


@pytest.mark.parametrize("region,host", [("global", "api.minimax.io"), ("cn", "api.minimax.cn")])
@pytest.mark.parametrize("language,boost", [("Auto", "auto"), ("Chinese", "Chinese")])
def test_mcp_call_maps_voice_language_and_region(region, host, language, boost, request_stub, monkeypatch):
    monkeypatch.setattr(requests, "get", lambda *a, **kw: pytest.fail("URL-only calls must not download"))
    output = call(region=region, language_type=language, model="speech-2.8-turbo", subtitle_enable=True)
    endpoint, key, payload = request_stub[0]
    assert endpoint == f"https://{host}/v1/t2a_v2"
    assert key == "test-token"
    assert payload == {
        "text": "Hello",
        "model": "speech-2.8-turbo",
        "voice_setting": {"voice_id": "narrator", "speed": 1.0, "vol": 1.0, "pitch": 0},
        "language_boost": boost,
        "audio_setting": {"format": "mp3", "sample_rate": 32000, "bitrate": 128000, "channel": 1},
        "stream": False,
        "output_format": "url",
        "subtitle_enable": True,
    }
    assert "**Audio URL**: https://example.com/audio.mp3" in output
    assert "**Subtitle URL**: https://example.com/subtitles.json" in output
    assert "**Duration (ms)**: 1500" in output
    assert "test-token" not in output


def test_optional_overrides_merge_defaults_and_reach_provider(request_stub):
    output = call(
        voice_setting={"speed": 1.2, "emotion": "calm"},
        audio_setting={"format": "wav", "sample_rate": 16000, "channel": 2},
        pronunciation_dict={"tone": ["Omg/Oh my god"]},
        voice_modify={"pitch": 5, "sound_effects": "spacious_echo"},
    )
    assert not output.startswith("Error:")
    assert request_stub[0][0] == "https://api.minimax.io/v1/t2a_v2"
    payload = request_stub[0][2]
    assert payload["voice_setting"] == {"voice_id": "narrator", "speed": 1.2, "vol": 1.0, "pitch": 0, "emotion": "calm"}
    assert payload["audio_setting"] == {"format": "wav", "sample_rate": 16000, "bitrate": 128000, "channel": 2}
    assert payload["pronunciation_dict"] == {"tone": ["Omg/Oh my god"]}
    assert payload["voice_modify"] == {"pitch": 5, "sound_effects": "spacious_echo"}


@pytest.mark.parametrize("audio_format", ["mp3", "wav", "flac", "pcm"])
def test_hex_audio_is_saved_with_selected_extension_and_subtitles(monkeypatch, tmp_path, audio_format):
    audio = b"test-audio-bytes"

    def request(endpoint, key, payload):
        assert payload["output_format"] == "hex"
        assert payload["audio_setting"]["format"] == audio_format
        return completed(audio.hex(), subtitle_file="https://example.com/subtitles.json")

    monkeypatch.setattr(minimax_tts, "_request", request)
    output = call(output_format="hex", output_dir=str(tmp_path / "audio"), audio_setting={"format": audio_format})
    assert "**Saved to**:" in output and "**Subtitle URL**:" in output
    assert "**Audio URL**:" not in output
    files = list((tmp_path / "audio").glob(f"*.{audio_format}"))
    assert len(files) == 1 and files[0].read_bytes() == audio


def test_hex_without_output_directory_uses_temporary_directory(monkeypatch, tmp_path):
    monkeypatch.setattr(minimax_tts.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(minimax_tts, "_request", lambda *args: completed(b"audio".hex()))
    assert "**Saved to**:" in call(output_format="hex")
    assert next((tmp_path / "qwen-mm-plugins").glob("*.mp3")).read_bytes() == b"audio"


@pytest.mark.parametrize("audio", ["not-hex", " "])
def test_invalid_hex_does_not_create_a_file(monkeypatch, tmp_path, audio):
    monkeypatch.setattr(minimax_tts, "_request", lambda *args: completed(audio))
    assert call(output_format="hex", output_dir=str(tmp_path)).startswith("Error:")
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "response,message",
    [
        ({"base_resp": {"status_code": 1004, "status_msg": "Authentication failed"}}, "[1004]"),
        ({"base_resp": "bad"}, "valid status"),
        ({"data": None}, "completed audio data"),
        (completed(status=1), "completed audio data"),
        (completed(audio="494433"), "audio URL"),
    ],
)
def test_provider_error_or_incomplete_response_is_reported(monkeypatch, response, message):
    monkeypatch.setattr(minimax_tts, "_request", lambda *args: response)
    output = call()
    assert output.startswith("Error:") and message in output


@pytest.mark.parametrize("status,attempts", [(401, 1), (403, 1), (429, 3), (503, 3)])
def test_http_retry_policy_and_sanitized_errors(monkeypatch, status, attempts):
    posts = []

    def post(*args, **kwargs):
        posts.append(kwargs)
        response = requests.Response()
        response.status_code = status
        response.url = "https://example.com/?private=test-token"
        return response

    monkeypatch.setattr(requests, "post", post)
    output = call()
    assert len(posts) == attempts
    assert f"HTTP {status}" in output
    assert "test-token" not in output


def test_malformed_json_is_reported(monkeypatch):
    response = requests.Response()
    response.status_code = 200
    response._content = b"not json"
    monkeypatch.setattr(requests, "post", lambda *args, **kwargs: response)
    assert "JSONDecodeError" in call()


def test_download_failure_preserves_generated_urls(monkeypatch, request_stub, tmp_path):
    def fail_download(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(api_dashscope, "save_url_to_dir", fail_download)
    output = call(output_dir=str(tmp_path), subtitle_enable=True)
    assert "**Audio URL**:" in output and "**Subtitle URL**:" in output
    assert "**Download failed**: OSError" in output
    assert "**Saved to**:" not in output
    assert len(request_stub) == 1


def test_mcp_to_http_download_keeps_distinct_syntheses(monkeypatch, tmp_path):
    """Exercise real HTTP POST/GET and filesystem I/O against a loopback provider."""
    posts, gets = [], []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            posts.append((self.path, self.headers.get("Authorization"), body))
            root = f"http://127.0.0.1:{self.server.server_port}"
            response = completed(f"{root}/{len(posts)}.mp3", subtitle_file=f"{root}/subtitles.json")
            payload = json.dumps(response).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self):
            gets.append((self.path, self.headers.get("Authorization")))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ID3-test-" + self.path.encode())

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setitem(minimax_tts._ENDPOINTS, "global", f"http://127.0.0.1:{server.server_port}/v1/t2a_v2")
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    try:
        for _ in range(2):
            output = call(output_dir=str(tmp_path / "audio"), subtitle_enable=True)
            assert "**Saved to**:" in output and "**Subtitle URL**:" in output
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert len(posts) == 2
    assert all(path == "/v1/t2a_v2" and auth == "Bearer test-token" for path, auth, _ in posts)
    assert all(payload["subtitle_enable"] is True for _, _, payload in posts)
    assert gets == [("/1.mp3", None), ("/2.mp3", None)]
    assert {path.read_bytes() for path in (tmp_path / "audio").glob("*.mp3")} == {
        b"ID3-test-/1.mp3",
        b"ID3-test-/2.mp3",
    }
