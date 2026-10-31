"""VOICEVOX engine (HTTP API) client.

The engine runs as a container next to the job (voicevox/voicevox_engine,
port 50021). Credit is required by the terms: "VOICEVOX:ずんだもん" etc.
"""

import time
import urllib.parse
from pathlib import Path

from . import http

SPEAKERS = {
    "zundamon": {"id": 3, "name": "ずんだもん", "credit": "VOICEVOX:ずんだもん"},
    "metan": {"id": 2, "name": "四国めたん", "credit": "VOICEVOX:四国めたん"},
}


class VoicevoxError(RuntimeError):
    pass


def wait_ready(base_url, timeout=180, request=http.request, sleep=time.sleep):
    deadline = time.monotonic() + timeout
    while True:
        try:
            return request("GET", base_url.rstrip("/") + "/version", retries=1, timeout=10).text()
        except http.HttpError:
            if time.monotonic() > deadline:
                raise VoicevoxError(f"VOICEVOX エンジンに接続できません: {base_url}") from None
            sleep(3)


def synthesize(text, speaker, path, base_url, speed=1.12, request=http.request):
    """Text -> WAV for one character. Returns the path."""
    if speaker not in SPEAKERS:
        raise VoicevoxError(f"未対応の話者です: {speaker}")
    base = base_url.rstrip("/")
    sid = SPEAKERS[speaker]["id"]
    query = request(
        "POST",
        f"{base}/audio_query?" + urllib.parse.urlencode({"text": text, "speaker": sid}),
        data=b"",
        retries=3,
        timeout=60,
    ).json()
    query["speedScale"] = speed
    query["intonationScale"] = 1.15
    query["postPhonemeLength"] = 0.25
    query["outputSamplingRate"] = 48000
    wav = request(
        "POST",
        f"{base}/synthesis?speaker={sid}",
        json_body=query,
        headers={"Accept": "audio/wav"},
        retries=3,
        timeout=120,
    ).body
    if not wav.startswith(b"RIFF"):
        raise VoicevoxError("音声データを受け取れませんでした")
    Path(path).write_bytes(wav)
    return Path(path)
