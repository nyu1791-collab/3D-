"""Locally drawn cutaway storyboard with silent timing placeholders; no cloud calls."""
import json
import random
import wave
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont


def _font(size):
    for path in ('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
                 'C:/Windows/Fonts/meiryo.ttc','/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc'):
        if Path(path).is_file():
            return ImageFont.truetype(path,size)
    return ImageFont.load_default(size=size)


def _arrow(draw,points,color,width=9):
    draw.line(points,fill=color,width=width,joint='curve')
    x,y=points[-1]
    draw.polygon([(x-12,y-18),(x+12,y-18),(x,y+6)],fill=color)


def _diagram(path,index):
    image=Image.new('RGB',(720,1280),'#101d31')
    draw=ImageDraw.Draw(image)
    draw.rounded_rectangle((25,25,695,1255),radius=30,fill='#edf3f5')
    draw.rounded_rectangle((48,48,300,92),radius=18,fill='#213957')
    draw.text((65,53),'しくみを、立体的に。',font=_font(23),fill='white')
    draw.text((52,105),'雨水と地下水',font=_font(38),fill='#142c48')
    draw.text((54,220),f'図解 {index} / 5　・　模式図 / 縮尺は任意',font=_font(17),fill='#557080')
    # Isometric soil block, with a visible saturated layer.
    a,b,c,d=(75,470),(385,386),(650,525),(340,610)
    draw.polygon([a,b,c,d],fill='#86b982')
    levels=[(0,100,'#997956','#aa8b66'),(100,245,'#c4a275','#d2b486'),(245,400,'#3988b0','#5eafd0')]
    for top,bottom,left,right in levels:
        draw.polygon([(a[0],a[1]+top),(d[0],d[1]+top),(d[0],d[1]+bottom),(a[0],a[1]+bottom)],fill=left)
        draw.polygon([(d[0],d[1]+top),(c[0],c[1]+top),(c[0],c[1]+bottom),(d[0],d[1]+bottom)],fill=right)
    randomizer=random.Random(71)
    for _ in range(95):
        x=randomizer.randint(370,620)
        y=int(610-(x-340)*.274)+randomizer.randint(110,235)
        draw.ellipse((x,y,x+5,y+3),fill='#b19268')
    draw.line([(d[0],d[1]+245),(c[0],c[1]+245)],fill='#d1f4ff',width=5)
    # Small house, on the land surface.
    draw.polygon([(150,380),(320,345),(320,470),(150,510)],fill='#e3d8b8')
    draw.polygon([(320,345),(415,397),(415,505),(320,470)],fill='#b9b097')
    draw.polygon([(127,387),(236,300),(345,354),(174,411)],fill='#d06c57')
    draw.polygon([(236,300),(344,272),(434,402),(345,354)],fill='#ab5045')
    for x,y in ((178,415),(246,398)):
        draw.polygon([(x,y),(x+35,y-8),(x+35,y+32),(x,y+40)],fill='#77bed3')
    # Well pipe and blue water inside it.
    draw.line([(553,468),(553,844)],fill='#334c62',width=28)
    draw.line([(553,474),(553,844)],fill='#8edcf4',width=14)
    draw.ellipse((528,450,578,477),fill='#d8e8ed',outline='#334c62',width=4)
    draw.line([(553,450),(553,425),(598,425)],fill='#334c62',width=15)
    draw.ellipse((589,419,608,434),fill='#66c7e5')
    for x,y in ((112,290),(415,270),(530,315)):
        _arrow(draw,[(x,y),(x,y+76)],'#63b4d5',6)
    _arrow(draw,[(450,530),(450,590),(438,651)],'#1bafd4')
    _arrow(draw,[(420,700),(435,742),(430,789)],'#1bafd4')
    focus=[(450,566),(425,727),(463,821),(553,793),(353,838)][index-1]
    draw.ellipse((focus[0]-27,focus[1]-27,focus[0]+27,focus[1]+27),outline='#ffe568',width=7)
    draw.text((70,1035),'青：水を含む層　黄：注目する場所',font=_font(19),fill='#416579')
    draw.rounded_rectangle((50,1080,670,1210),radius=16,fill='#dce7eb')
    draw.text((64,1220),'音声なし・構成デモ / クラウド生成は未使用',font=_font(17),fill='#607c8b')
    image.save(path)


def create(output):
    output=Path(output).expanduser().resolve()
    assets=output/'assets'
    assets.mkdir(parents=True,exist_ok=True)
    captions=[
        ('地面にしみ込む雨水','雨水の一部は、地面にしみ込んでいきます。','zoom_in'),
        ('土や岩のすき間','水は、土や岩のすき間を通って移動します。','pan_down'),
        ('地下水面','深いところでは、すき間が水で満たされた層があります。','zoom_in'),
        ('井戸からくみ上げる','井戸は、その地下水をくみ上げて利用します。','pan_down'),
        ('時間がかかる','雨が地下水を補う速さは、地層や場所によって違います。','zoom_out')]
    scenes=[]
    for index,(label,narration,motion) in enumerate(captions,1):
        if not (assets/f'scene-{index:03d}.png').is_file():
            _diagram(assets/f'scene-{index:03d}.png',index)
        if not (assets/f'scene-{index:03d}.wav').is_file():
            with wave.open(str(assets/f'scene-{index:03d}.wav'),'wb') as audio:
                audio.setnchannels(1)
                audio.setsampwidth(2)
                audio.setframerate(24000)
                audio.writeframes(b'\0\0'*(24000*6))
        scenes.append({'scene_number':index,'narration':narration,'imagen_prompt':'Local schematic demonstration; no image API used.',
                       'highlight_label':label,'label_x':0,'label_y':-.43,'camera_motion':motion})
    plan={'title':'雨水が地下水になるまで','hook_text':'地下の水は、どこから来る？','scenes':scenes,
          'demo':True,'audio':'silent timing placeholders; no narration generated',
          'notes':'自作の模式図。地層の厚さ・水位・所要時間の数値は示していません。'}
    (output/'plan.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2),encoding='utf-8')
    return plan,assets
