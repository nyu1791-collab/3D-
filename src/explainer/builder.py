"""Editable CapCut timelines from images and real narration durations."""
import json
from pathlib import Path
import shutil
import subprocess
import uuid
import wave
from datetime import datetime


def audio_seconds(path):
    """Use WAV sample frames, with a media-header fallback for other audio formats."""
    try:
        with wave.open(str(path), 'rb') as audio:
            return audio.getnframes() / audio.getframerate()
    except (wave.Error, EOFError):
        result = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                                 '-of', 'default=noprint_wrappers=1:nokey=1', str(path)],
                                capture_output=True, text=True, check=True)
        return float(result.stdout.strip())


def scene_timeline(plan, assets):
    """Return available scenes on one narration timeline; unavailable assets remain noted."""
    assets = Path(assets).expanduser().resolve()
    rows, omitted, position = [], [], 0.0
    for index, scene in enumerate(plan.get('scenes') or [], 1):
        number = scene.get('scene_number', index) if isinstance(scene, dict) else index
        try:
            if not isinstance(scene, dict):
                raise ValueError('シーンの素材指定を読み取れません')
            image = assets / f'scene-{int(number):03d}.png'
            audio = assets / f'scene-{int(number):03d}.wav'
            if not image.is_file() or not audio.is_file():
                raise FileNotFoundError('画像またはナレーション素材がまだありません')
            duration = audio_seconds(audio)
            if duration <= 0:
                raise ValueError('ナレーションの長さを取得できませんでした')
            rows.append({'scene_number': number, 'image': str(image), 'audio': str(audio),
                         'start': position, 'duration': duration, 'scene': scene})
            position += duration
        except (OSError, ValueError, TypeError, subprocess.SubprocessError) as error:
            omitted.append({'scene_number': number, 'feature': 'scene', 'reason': str(error)})
    return rows, omitted


def _color(value, default):
    if not value:
        return default
    if isinstance(value, str):
        value = value.lstrip('#')
        return tuple(int(value[i:i+2], 16) / 255 for i in (0, 2, 4))
    return tuple(value)


def build(plan, assets, drafts_dir, settings):
    """Create a new self-contained project. Static-image motion is pseudo-3D only."""
    import pycapcut as cc

    rows, omitted = scene_timeline(plan, assets)
    if not rows:
        raise ValueError('利用できる画像とナレーションの組がありません。取得済み素材は保持しています')
    root = Path(drafts_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    name = 'explainer-' + datetime.now().strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:8]
    script = cc.DraftFolder(str(root)).create_draft(
        name, int(settings.get('width', 1080)), int(settings.get('height', 1920)),
        fps=int(settings.get('fps', 30)))
    project = root / name
    media = project / 'media'
    media.mkdir()
    script.add_track(cc.TrackType.video, 'main_visual')
    script.add_track(cc.TrackType.audio, 'narration')
    script.add_track(cc.TrackType.text, 'captions')
    script.add_track(cc.TrackType.text, 'labels')
    font_name = settings.get('font') or ''
    font = getattr(cc.FontType, font_name, None)
    if font_name and font is None:
        omitted.append({'feature': 'font', 'reason': f'{font_name} が見つからないため標準フォントを使用'})
    try:
        caption_color = _color(settings.get('caption_color'), (1.0, 1.0, 1.0))
    except (ValueError, TypeError):
        caption_color = (1.0, 1.0, 1.0)
        omitted.append({'feature': 'caption_color', 'reason': '標準の白色を使用'})
    try:
        label_color = _color(settings.get('label_color'), (1.0, 0.89, 0.35))
    except (ValueError, TypeError):
        label_color = (1.0, 0.89, 0.35)
        omitted.append({'feature': 'label_color', 'reason': '標準の黄色を使用'})

    timeline = []
    current_us = 0
    for index, row in enumerate(rows, 1):
        scene = row['scene']
        number = row['scene_number']
        image = media / f'{index:03d}.png'
        audio = media / f'{index:03d}.wav'
        duration_us = round(row['duration'] * cc.SEC)
        timerange = cc.Timerange(current_us, duration_us)
        try:
            # Each new project owns its media; source assets and existing drafts stay intact.
            shutil.copy2(row['image'], image)
            shutil.copy2(row['audio'], audio)
            sound = cc.AudioMaterial(str(audio))
            # WAV frame count is authoritative rather than millisecond-rounded metadata.
            sound.duration = duration_us
            narration = cc.AudioSegment(sound, timerange, volume=1.0)
            visual = cc.VideoSegment(cc.VideoMaterial(str(image)), timerange)
        except Exception as error:
            omitted.append({'scene_number': number, 'feature': 'scene_media', 'reason': str(error)})
            continue
        motion = scene.get('camera_motion', 'zoom_in')
        try:
            if motion == 'zoom_in':
                visual.add_keyframe(cc.KeyframeProperty.uniform_scale, 0, 1.0)
                visual.add_keyframe(cc.KeyframeProperty.uniform_scale, duration_us, 1.12)
            elif motion == 'zoom_out':
                visual.add_keyframe(cc.KeyframeProperty.uniform_scale, 0, 1.12)
                visual.add_keyframe(cc.KeyframeProperty.uniform_scale, duration_us, 1.0)
            elif motion == 'pan_down':
                visual.add_keyframe(cc.KeyframeProperty.uniform_scale, 0, 1.12)
                visual.add_keyframe(cc.KeyframeProperty.uniform_scale, duration_us, 1.12)
                visual.add_keyframe(cc.KeyframeProperty.position_y, 0, 0.08)
                visual.add_keyframe(cc.KeyframeProperty.position_y, duration_us, -0.08)
            elif motion not in ('static', None, ''):
                omitted.append({'scene_number': number, 'feature': 'camera_motion',
                                'reason': f'{motion} は未対応のため静止画として配置'})
        except Exception as error:
            omitted.append({'scene_number': number, 'feature': 'camera_motion', 'reason': str(error)})
        script.add_segment(visual, 'main_visual')
        script.add_segment(narration, 'narration')
        text = str(scene.get('narration') or '')
        if text:
            try:
                script.add_segment(cc.TextSegment(
                    text, timerange, font=font,
                    style=cc.TextStyle(size=float(settings.get('caption_size', 8)), bold=True,
                                       color=caption_color, align=1, auto_wrapping=True, max_line_width=0.8),
                    clip_settings=cc.ClipSettings(transform_y=float(settings.get('caption_y', -0.76))),
                    border=cc.TextBorder(width=18)), 'captions')
            except Exception as error:
                omitted.append({'scene_number': number, 'feature': 'caption', 'reason': str(error)})
        label = scene.get('highlight_label') or ''
        if label:
            try:
                script.add_segment(cc.TextSegment(
                    str(label), timerange, font=font,
                    style=cc.TextStyle(size=float(settings.get('label_size', 7)), bold=True,
                                       color=label_color, align=1, auto_wrapping=True, max_line_width=0.7),
                    clip_settings=cc.ClipSettings(
                        transform_x=float(scene.get('label_x', settings.get('label_x', 0))),
                        transform_y=float(scene.get('label_y', settings.get('label_y', -0.55)))),
                    border=cc.TextBorder(width=18)), 'labels')
            except Exception as error:
                omitted.append({'scene_number': number, 'feature': 'label', 'reason': str(error)})
        timeline.append({'scene_number': number, 'start': current_us / cc.SEC,
                         'duration': duration_us / cc.SEC, 'image': str(image), 'audio': str(audio),
                         'caption': text, 'camera_motion': motion})
        current_us += duration_us
    if not timeline:
        raise ValueError(f'読み込める素材がありません。作成途中のフォルダを保持しています: {project}')
    hook = plan.get('hook_text') or plan.get('title') or ''
    if hook:
        try:
            script.add_track(cc.TrackType.text, 'hook')
            script.add_segment(cc.TextSegment(
                str(hook), cc.Timerange(0, min(current_us, 3 * cc.SEC)), font=font,
                style=cc.TextStyle(size=float(settings.get('hook_size', 10)), bold=True,
                                   color=label_color, align=1, auto_wrapping=True, max_line_width=0.82),
                clip_settings=cc.ClipSettings(transform_y=0.72), border=cc.TextBorder(width=18)), 'hook')
        except Exception as error:
            omitted.append({'feature': 'hook_text', 'reason': str(error)})
    script.save()
    result = {'status': 'created_not_opened_in_capcut', 'draft': str(project),
              'duration': current_us / cc.SEC, 'scene_count': len(timeline), 'omitted': omitted,
              'timeline': timeline, 'subtitle_timing': 'narration scene duration; not word alignment',
              'visual_motion': 'keyframed still images; not a generated 3D video'}
    (project / 'explainer-timeline.json').write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return result
