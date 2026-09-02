"""Smoke test for the video-edit capability's generation MCP server.

conftest auto-discovers qwen_mm_plugins_video_edit (it scans src/capabilities/*/ for the server
package), so it imports like any other server. Handlers hit remote DashScope APIs, so we only
exercise discovery + the advertised schema/handler surface here (no live calls).
"""

import sys
import types

import qwen_mm_plugins_video_edit as ve

GENERATION_TOOLS = {
    "qwen_image",
    "qwen_tts",
    "minimax_tts",
    "wan_s2v",
    "wan_t2v",
    "happyhorse",
}


def test_lists_the_generation_tools():
    names = {t["name"] for t in ve.list_tools()}
    assert names == GENERATION_TOOLS


def test_every_tool_has_schema_and_handler():
    for tool in ve.list_tools():
        assert tool["inputSchema"]["type"] == "object"
        assert callable(ve.get_handler(tool["name"]))


def test_unknown_tool_has_no_handler():
    assert ve.get_handler("does_not_exist") is None


def test_minimax_tts_posts_settings_and_decodes_hex(monkeypatch, tmp_path):
    import requests
    from qwen_mm_plugins_video_edit.tools import minimax_tts

    calls = []

    class Response:
        status_code = 200

        @staticmethod
        def raise_for_status():
            return None

        @staticmethod
        def json():
            return {
                "data": {"audio": "494433", "status": 2},
                "extra_info": {"audio_length": 1250, "usage_characters": 11},
                "base_resp": {"status_code": 0, "status_msg": "success"},
            }

    def post(url, **kwargs):
        calls.append((url, kwargs))
        return Response()

    monkeypatch.setattr(requests, "post", post)
    monkeypatch.setattr(minimax_tts, "get_env", lambda name: "test-token")

    result = minimax_tts.handle(
        {
            "text": "Hello world",
            "model": "speech-2.8-hd",
            "region": "global_en",
            "voice_setting": {"voice_id": "English_expressive_narrator", "speed": 1.1},
            "audio_setting": {
                "sample_rate": 32000,
                "bitrate": 128000,
                "format": "mp3",
                "channel": 1,
            },
            "language_boost": "English",
            "output_format": "hex",
            "output_dir": str(tmp_path),
        }
    )

    assert calls[0][0] == "https://api.minimax.io/v1/t2a_v2"
    assert calls[0][1]["headers"]["Authorization"] == "Bearer test-token"
    assert calls[0][1]["json"] == {
        "model": "speech-2.8-hd",
        "text": "Hello world",
        "stream": False,
        "output_format": "hex",
        "voice_setting": {"voice_id": "English_expressive_narrator", "speed": 1.1},
        "audio_setting": {
            "sample_rate": 32000,
            "bitrate": 128000,
            "format": "mp3",
            "channel": 1,
        },
        "subtitle_enable": False,
        "language_boost": "English",
    }
    audio_files = list(tmp_path.glob("minimax_tts_*.mp3"))
    assert len(audio_files) == 1
    assert audio_files[0].read_bytes() == b"ID3"
    assert "**Saved to**" in result[0]["text"]


def test_minimax_tts_uses_china_endpoint_for_url_output(monkeypatch):
    import requests
    from qwen_mm_plugins_video_edit.tools import minimax_tts

    calls = []

    class Response:
        status_code = 200

        @staticmethod
        def raise_for_status():
            return None

        @staticmethod
        def json():
            return {
                "data": {"audio": "https://cdn.example.test/audio.wav", "status": 2},
                "base_resp": {"status_code": 0, "status_msg": "success"},
            }

    def post(url, **kwargs):
        calls.append((url, kwargs))
        return Response()

    monkeypatch.setattr(requests, "post", post)
    monkeypatch.setattr(minimax_tts, "get_env", lambda name: "test-token")

    result = minimax_tts.handle(
        {
            "text": "Hello",
            "region": "cn_zh",
            "voice_setting": {"voice_id": "voice-id"},
            "audio_setting": {"format": "wav"},
            "output_format": "url",
        }
    )

    assert calls[0][0] == "https://api.minimaxi.com/v1/t2a_v2"
    assert "https://cdn.example.test/audio.wav" in result[0]["text"]


def test_minimax_tts_schema_lists_models_and_audio_formats():
    from qwen_mm_plugins_video_edit.tools import minimax_tts

    schema = minimax_tts.MiniMaxTtsArgs.model_json_schema()
    assert schema["properties"]["model"]["default"] == "speech-2.8-hd"
    assert schema["properties"]["model"]["enum"] == [
        "speech-2.8-hd",
        "speech-2.8-turbo",
        "speech-2.6-hd",
        "speech-2.6-turbo",
        "speech-02-hd",
        "speech-02-turbo",
        "speech-01-hd",
        "speech-01-turbo",
    ]
    assert schema["$defs"]["MiniMaxAudioSetting"]["properties"]["format"]["enum"] == [
        "mp3",
        "wav",
        "flac",
        "pcm",
    ]


def test_wan_s2v_detect_surfaces_root_api_error(monkeypatch):
    import requests

    from qwen_mm_plugins_video_edit.tools import wan_s2v

    class Response:
        status_code = 400

        @staticmethod
        def json():
            return {"code": "InvalidURL", "message": "image is unreachable", "request_id": "req-1"}

    monkeypatch.setattr(requests, "post", lambda *args, **kwargs: Response())
    monkeypatch.setattr(wan_s2v, "retry_call", lambda fn, *args, **kwargs: fn(*args, **kwargs))

    result = wan_s2v._detect("https://example.com/missing.png", "key")
    assert "InvalidURL" in result[0]["text"]
    assert "image is unreachable" in result[0]["text"]
    assert "req-1" in result[0]["text"]


def test_wan_27_translates_existing_size_interface(monkeypatch):
    from qwen_mm_plugins_video_edit.tools import wan_t2v
    from shared import api_dashscope

    calls = []

    class VideoSynthesis:
        @staticmethod
        def call(**kwargs):
            calls.append(kwargs)
            return types.SimpleNamespace(
                status_code=200,
                output=types.SimpleNamespace(task_status="SUCCEEDED", video_url="https://example.com/video.mp4"),
            )

    dashscope = types.ModuleType("dashscope")
    dashscope.VideoSynthesis = VideoSynthesis
    dashscope.base_http_api_url = None
    monkeypatch.setitem(sys.modules, "dashscope", dashscope)
    monkeypatch.setattr(wan_t2v, "get_env", lambda name: "key")
    monkeypatch.setattr(api_dashscope, "retry_call", lambda fn, **kwargs: fn(**kwargs))

    result = wan_t2v.handle(
        {
            "mode": "text_to_video",
            "prompt": "a cat runs",
            "size": "720*1280",
        }
    )

    assert not result[0]["text"].startswith("Error:")
    assert calls[0]["resolution"] == "720P"
    assert calls[0]["ratio"] == "9:16"
    assert "size" not in calls[0]


def test_wan_t2v_schema_keeps_size_parameter():
    from qwen_mm_plugins_video_edit.tools import wan_t2v

    schema = wan_t2v.WanT2vArgs.model_json_schema()
    assert "size" in schema["properties"]
    assert "resolution" not in schema["properties"]
    assert "ratio" not in schema["properties"]
