"""Optional local MP4 output from the same image/narration scene timeline."""
from pathlib import Path
import subprocess
import pysubs2
from . import ffmpeg_recipes as fr
from .builder import scene_timeline


def _text(value):
    return str(value).replace('\\','＼').replace('{','（').replace('}','）').replace('\n',r'\N')


def _color(value, default):
    try:
        if isinstance(value,str):
            value=value.lstrip('#')
            return pysubs2.Color(*(int(value[i:i+2],16) for i in (0,2,4)))
        if value:
            return pysubs2.Color(*(round(float(c)*255) for c in value))
    except (ValueError,TypeError):
        pass
    return default


def _position(x,y,width,height):
    # Match CapCut's centered canvas coordinates: right/up are positive.
    return round((float(x)+1)*width/2),round((1-float(y))*height/2)


def _size(value,height):
    # Keep the former 32px caption at 1280px height for CapCut size 8.
    return max(1,round(float(value)*height/320))


def render(plan,assets,output,settings):
    output=Path(output).expanduser().resolve()
    output.mkdir(parents=True,exist_ok=True)
    rows,omitted=scene_timeline(plan,assets)
    if not rows:
        raise ValueError('画像と音声の組がありません。素材を保持しています')
    width,height,fps=int(settings.get('width',720)),int(settings.get('height',1280)),int(settings.get('fps',30))
    folder=output/'render-scenes'
    folder.mkdir(exist_ok=True)
    captions=pysubs2.SSAFile()
    font=settings.get('font_family','Noto Sans CJK JP')
    caption_color=_color(settings.get('caption_color'),pysubs2.Color(255,255,255))
    label_color=_color(settings.get('label_color'),pysubs2.Color(255,229,104))
    caption_x,caption_y=_position(0,settings.get('caption_y',-.76),width,height)
    hook_x,hook_y=_position(0,.72,width,height)
    clips=[]
    for index,row in enumerate(rows):
        subs=pysubs2.SSAFile()
        subs.info.update(PlayResX=str(width),PlayResY=str(height),WrapStyle='0')
        subs.styles['Default']=pysubs2.SSAStyle(fontname=font,fontsize=_size(settings.get('caption_size',8),height),
             primarycolor=caption_color,bold=True,outline=2,shadow=0,alignment=5,marginl=40,marginr=40)
        subs.styles['Label']=pysubs2.SSAStyle(fontname=font,fontsize=_size(settings.get('label_size',7),height),
             primarycolor=label_color,bold=True,outline=2,shadow=0,alignment=5,marginl=40,marginr=40)
        subs.styles['Hook']=pysubs2.SSAStyle(fontname=font,fontsize=_size(settings.get('hook_size',10),height),
             primarycolor=label_color,bold=True,outline=2,shadow=0,alignment=5,marginl=40,marginr=40)
        scene=row['scene']
        duration=row['duration']
        text=_text(scene.get('narration',''))
        subs.events.append(pysubs2.SSAEvent(start=0,end=round(duration*1000),
            text=rf'{{\an5\pos({caption_x},{caption_y})}}'+text))
        captions.events.append(pysubs2.SSAEvent(start=round(row['start']*1000),end=round((row['start']+duration)*1000),text=text))
        label=scene.get('highlight_label')
        if label:
            x,y=_position(scene.get('label_x',settings.get('label_x',0)),
                          scene.get('label_y',settings.get('label_y',-.55)),width,height)
            subs.events.append(pysubs2.SSAEvent(start=0,end=round(duration*1000),
                text=rf'{{\an5\pos({x},{y})}}'+_text(label),style='Label'))
        if index==0:
            hook=plan.get('hook_text') or plan.get('title','')
            subs.events.append(pysubs2.SSAEvent(start=0,end=round(min(3,duration)*1000),
                text=rf'{{\an5\pos({hook_x},{hook_y})}}'+_text(hook),style='Hook'))
        name=f'scene-{index:03d}'
        subs.save(str(folder/(name+'.ass')))
        frames=max(1,round(duration*fps))
        quality=settings.get('quality','standard')
        motion=fr.ken_burns(width,height,fps,frames,scene.get('camera_motion','zoom_in'),
                            oversample=2 if quality=='draft' else 4)
        vf=f"{motion},ass={name}.ass,format=yuv420p"
        clip=folder/(name+'.mp4')
        if not clip.is_file():
            with (folder/'render.log').open('ab') as log:
                subprocess.run(['ffmpeg','-nostdin','-v','error','-y','-loop','1','-i',row['image'],
                    '-i',row['audio'],'-t',str(duration),'-vf',vf,'-af',fr.voice_chain(),
                    *fr.delivery_args(quality,settings.get('encoder','libx264')),name+'.next.mp4'],cwd=folder,stdout=log,stderr=subprocess.STDOUT,check=True)
            (folder/(name+'.next.mp4')).replace(clip)
        clips.append(clip.name)
    (folder/'concat.txt').write_text('\n'.join("file '"+name+"'" for name in clips),encoding='utf-8')
    temporary=output/'video.next.mp4'
    subprocess.run(['ffmpeg','-nostdin','-v','error','-y','-f','concat','-safe','0','-i','concat.txt',
                    '-c','copy','-movflags','+faststart',str(temporary)],cwd=folder,check=True)
    temporary.replace(output/'video.mp4')
    captions.save(str(output/'captions.srt'))
    return {'video':str(output/'video.mp4'),'scenes':len(rows),'duration':sum(r['duration'] for r in rows),'omitted':omitted}
