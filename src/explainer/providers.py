"""Explicit Google generation routes; completed files are reused without extra calls."""
import json
import os
from pathlib import Path
import random
import socket
import time
import urllib.error

PROJECT = 'project-fdadb4dd-cb77-4270-9cd'
TEMPORARY_HTTP = {429, 500, 502, 503, 504}


def _usage(output, settings, row):
    root = Path(settings.get('usage_dir') or output)
    root.mkdir(parents=True, exist_ok=True)
    with (root / 'request-usage.jsonl').open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(row, ensure_ascii=False) + '\n')


def _status(error):
    code = getattr(error, 'code', None)
    if callable(code):
        code = code()
    if hasattr(code, 'value'):
        code = code.value
    if isinstance(code, tuple):
        code = code[0]
    try:
        return int(code)
    except (TypeError, ValueError):
        return None


def _temporary(error, status):
    if status is not None:
        return status in TEMPORARY_HTTP
    return isinstance(error, (ConnectionError, TimeoutError, socket.timeout, urllib.error.URLError)) or type(error).__name__ in {
        'ConnectError', 'ConnectTimeout', 'ReadTimeout', 'WriteTimeout', 'RemoteProtocolError', 'DeadlineExceeded'
    }


def _request(operation, output, settings, metadata, call):
    for attempt in range(1, 4):
        started = time.monotonic()
        row = {'operation': operation, 'attempt': attempt, 'status': 'failed', **metadata}
        retry_after = 0.0
        try:
            response = call()
            row['status'] = 'received'
            usage = getattr(response, 'usage_metadata', None)
            if usage:
                if hasattr(usage, 'model_dump'):
                    usage = usage.model_dump(mode="json", exclude_none=True)
                if isinstance(usage, dict):
                    row['usage'] = usage
            return response
        except Exception as error:
            status = _status(error)
            row.update(error_type=type(error).__name__, http_status=status)
            if not _temporary(error, status) or attempt == 3:
                raise
            headers = getattr(getattr(error, 'response', None), 'headers', {})
            try:
                retry_after = max(0, float(headers.get('retry-after', 0)))
            except (ValueError, TypeError, AttributeError):
                pass
        finally:
            row['elapsed_seconds'] = round(time.monotonic() - started, 3)
            _usage(output, settings, row)
        time.sleep(max(retry_after, (15 if attempt == 1 else 45) + random.uniform(0, 5)))


def _cloud_client(settings):
    from google import genai
    from google.genai import types
    import google.auth
    name = settings.get('cloud_client', 'vertex')
    if name not in ('enterprise', 'vertex'):
        raise ValueError('cloud_client は enterprise または vertex を指定してください')
    flag = 'enterprise' if name == 'enterprise' else 'vertexai'
    project = settings.get('project') or PROJECT
    credentials, _ = google.auth.default(
        scopes=['https://www.googleapis.com/auth/cloud-platform'], quota_project_id=project)
    try:
        # Explicit Cloud credentials make the SDK ignore ambient API keys;
        # keep environment variables intact for parallel AI Studio requests.
        return genai.Client(**{flag: True}, credentials=credentials, project=project,
                            location=settings.get('location') or 'us-central1',
                            http_options=types.HttpOptions(timeout=180000,
                                retry_options=types.HttpRetryOptions(attempts=1)))
    except TypeError as error:
        raise RuntimeError(f'Google Gen AI SDKが {flag} 引数に対応していません。google-genaiを更新するか、導入版に合わせてcloud_clientを明示してください') from error


def _text_client(settings):
    from google import genai
    from google.genai import types
    route = settings.get('gemini_route', 'aistudio')
    if route == 'aistudio':
        key = os.getenv('GEMINI_API_KEY')
        if not key:
            raise ValueError('AI Studio経路には GEMINI_API_KEY を設定してください')
        # Explicitly select Developer API even if the shell has a Cloud default.
        flag = 'vertexai' if settings.get('cloud_client', 'vertex') == 'vertex' else 'enterprise'
        return genai.Client(api_key=key, **{flag:False}, http_options=types.HttpOptions(
            timeout=180000, retry_options=types.HttpRetryOptions(attempts=1)))
    if route == 'vertex':
        return _cloud_client(settings)
    raise ValueError('gemini_route は aistudio または vertex を指定してください')


def _json(path, value):
    temporary = path.with_name(path.stem + '.pending.json')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def plan(topic, output, settings):
    """Create one structured scene plan; duration and scene count are goals."""
    from google.genai import types
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    path = output / 'plan.json'
    model = settings.get('gemini_model') or 'gemini-3.8-flash'
    route = settings.get('gemini_route', 'aistudio')
    metadata = {'route': route, 'model': model,
                'project': settings.get('project') or PROJECT if route == 'vertex' else None}
    if path.is_file():
        _usage(output, settings, {'operation': 'plan', 'status': 'reused', 'attempt': 0, **metadata})
        return json.loads(path.read_text(encoding='utf-8'))
    schema = {'type': 'object', 'properties': {
        'title': {'type': 'string'}, 'hook_text': {'type': 'string'},
        'scenes': {'type': 'array', 'items': {'type': 'object', 'properties': {
            'scene_number': {'type': 'integer'}, 'narration': {'type': 'string'},
            'imagen_prompt': {'type': 'string'}, 'highlight_label': {'type': 'string'},
            'label_x': {'type': 'number'}, 'label_y': {'type': 'number'},
            'camera_motion': {'type': 'string', 'enum': ['zoom_in', 'pan_down', 'zoom_out']}
        }, 'required': ['scene_number', 'narration', 'imagen_prompt']}}
    }, 'required': ['title', 'hook_text', 'scenes']}
    prompt = (
        f'テーマ「{topic}」の日本語の短い図解解説動画を作ってください。'
        f'目標は約{settings.get("target_seconds",30)}秒、{settings.get("scene_goal",5)}シーンですが目安です。'
        '意味が通る構成を優先し、数合わせのシーンや根拠のない断定、数字を捏造しないでください。'
        '冒頭で対象と知る理由を具体的に伝え、各シーンに短いナレーションと図解の指示を付けます。'
        'imagen_promptは英語で3D isometric cross-section rendering, cutaway view, clean lighting, '
        'vertical 9:16を含めます。全シーンで対象の形、断面位置、配色、視点を揃え、共通の外観説明を各画像プロンプトにも含めます。'
        '図は概念図として単純化し、画像内に文字を描かず、'
        '注目ラベルはhighlight_labelとして日本語で別に返します。'
        'label_x/label_yは画面中心が0、左と下が-1、右と上が1のレイアウト希望値です。検出済み座標とはしません。'
        'camera_motionはzoom_in, pan_down, zoom_outのいずれか。'
        '科学・医療・建築などの説明では不確かな点や簡略化をナレーションでも適切に表現してください。'
    )
    with _text_client(settings) as client:
        response = _request('plan', output, settings, metadata, lambda: client.models.generate_content(
            model=model, contents=prompt, config=types.GenerateContentConfig(
                response_mime_type='application/json', response_schema=schema, temperature=0.65)))
    text = response.text or ''
    (output / 'plan-response.txt').write_text(text, encoding='utf-8')
    value = json.loads(text)
    if not isinstance(value, dict) or not isinstance(value.get('scenes'), list):
        raise ValueError('台本のシーン一覧を読み取れません。応答本文は保存しています')
    _json(path, value)
    return value


def image(prompt, path, settings):
    """Generate one image on the explicitly selected Cloud image backend."""
    from google.genai import types
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    backend = settings.get('image_backend', 'gemini')
    model = settings.get('image_model') or 'gemini-2.5-flash-image'
    metadata = {'route': 'vertex', 'model': model, 'project': settings.get('project') or PROJECT,
                'location': settings.get('location') or 'us-central1', 'requested_images': 1}
    if path.is_file():
        _usage(path.parent, settings, {'operation': 'image', 'status': 'reused', 'attempt': 0, **metadata})
        return path
    temporary = path.with_name(path.stem + '.pending.png')
    try:
        with _cloud_client(settings) as client:
            if backend == 'imagen':
                response = _request('image', path.parent, settings, metadata, lambda: client.models.generate_images(
                    model=model, prompt=prompt, config=types.GenerateImagesConfig(
                        number_of_images=1, aspect_ratio='9:16', output_mime_type='image/png')))
                generated = response.generated_images or []
                if not generated or generated[0].image is None:
                    raise RuntimeError('画像を取得できませんでした。別モデルへの切り替えは行っていません')
                generated[0].image.save(str(temporary))
            elif backend == 'gemini':
                response = _request('image', path.parent, settings, metadata, lambda: client.models.generate_content(
                    model=model, contents=prompt, config=types.GenerateContentConfig(
                        response_modalities=['IMAGE'], image_config=types.ImageConfig(aspect_ratio='9:16'))))
                parts = response.parts or []
                generated = next((part.as_image() for part in parts if part.inline_data), None)
                if generated is None:
                    raise RuntimeError('画像を取得できませんでした。別モデルへの切り替えは行っていません')
                generated.save(str(temporary))
            else:
                raise ValueError('image_backend は gemini または imagen を指定してください')
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return path


def speech(text, path, settings):
    """Cloud TTS LINEAR16 audio is stored as WAV; no ASR timing is invented."""
    import google.auth
    from google.cloud import texttospeech
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    project = settings.get('project') or PROJECT
    voice = settings.get('tts_voice') or 'ja-JP-Neural2-C'
    metadata = {'route': 'cloud_tts', 'project': project, 'model': voice,
                'requested_characters': len(text)}
    if path.is_file():
        _usage(path.parent, settings, {'operation': 'speech', 'status': 'reused', 'attempt': 0, **metadata})
        return path
    credentials, _ = google.auth.default(
        scopes=['https://www.googleapis.com/auth/cloud-platform'], quota_project_id=project)
    with texttospeech.TextToSpeechClient(credentials=credentials) as client:
        response = _request('speech', path.parent, settings, metadata, lambda: client.synthesize_speech(
            input=texttospeech.SynthesisInput(text=text),
            voice=texttospeech.VoiceSelectionParams(language_code=settings.get('language','ja-JP'), name=voice),
            audio_config=texttospeech.AudioConfig(audio_encoding=texttospeech.AudioEncoding.LINEAR16,
                speaking_rate=float(settings.get('tts_rate',1.15))), retry=None, timeout=180))
    if not response.audio_content:
        raise RuntimeError('ナレーション音声を取得できませんでした')
    temporary = path.with_name(path.stem + '.pending.wav')
    temporary.write_bytes(response.audio_content)
    temporary.replace(path)
    return path
