"""Resumable scene assets and output jobs, independent of other repositories."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from filelock import FileLock
import yaml
from dotenv import load_dotenv

ROOT=Path(__file__).resolve().parents[2]
load_dotenv(ROOT/'.env')


def settings(path=None):
    value=yaml.safe_load((ROOT/'config/default.yaml').read_text(encoding='utf-8'))
    if path:
        extra=yaml.safe_load(Path(path).expanduser().read_text(encoding='utf-8')) or {}
        value.update({k:v for k,v in extra.items() if k in value})
    value['project']=os.getenv('GOOGLE_CLOUD_PROJECT') or value['project']
    value['drafts_dir']=os.getenv('CAPCUT_DRAFTS_DIR') or value.get('drafts_dir','')
    return value


def home():
    root=Path(os.getenv('EXPLAINER_DATA_DIR') or Path.home()/'.3d-explainer').expanduser().resolve()
    root.mkdir(parents=True,exist_ok=True,mode=0o700)
    return root


def key(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True).encode()).hexdigest()


def write(path,value):
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    temporary.replace(path)


def connect():
    db=sqlite3.connect(home()/'pipeline.sqlite3',timeout=30)
    db.row_factory=sqlite3.Row
    db.execute('CREATE TABLE IF NOT EXISTS jobs (output TEXT PRIMARY KEY,status TEXT,updated REAL,details TEXT)')
    db.execute('CREATE TABLE IF NOT EXISTS steps (id INTEGER PRIMARY KEY,output TEXT,operation TEXT,status TEXT,seconds REAL,message TEXT)')
    return db


def record(output,status,details):
    with connect() as db:
        db.execute('INSERT INTO jobs VALUES (?,?,?,?) ON CONFLICT(output) DO UPDATE SET status=excluded.status,updated=excluded.updated,details=excluded.details',
                   (str(output),status,time.time(),json.dumps(details,ensure_ascii=False)))


def stage(output,operation,call):
    started=time.monotonic()
    try:
        value=call()
    except Exception as error:
        with connect() as db:
            db.execute('INSERT INTO steps(output,operation,status,seconds,message) VALUES (?,?,?,?,?)',
                       (str(output),operation,'failed',time.monotonic()-started,str(error)))
        raise
    with connect() as db:
        db.execute('INSERT INTO steps(output,operation,status,seconds,message) VALUES (?,?,?,?,?)',
                   (str(output),operation,'finished',time.monotonic()-started,''))
    return value


def generate_assets(plan,output,cfg):
    from . import providers
    output=Path(output)
    revision=key({'plan':plan,'image':[cfg['image_backend'],cfg['image_model'],cfg['project'],cfg['location']],
                  'voice':[cfg['tts_voice'],cfg['tts_rate'],cfg['language'],cfg['project']]})[:20]
    assets=output/'assets'/revision
    assets.mkdir(parents=True,exist_ok=True)
    cache=home()/'cache'
    cache.mkdir(exist_ok=True)
    configured={**cfg,'usage_dir':str(output)}
    def material(scene):
        errors=[]
        number=int(scene['scene_number'])
        operations=[('image',scene.get('imagen_prompt',''),'png',providers.image,
                     [cfg['image_backend'],cfg['image_model'],cfg['project'],cfg['location']]),
                    ('speech',scene.get('narration',''),'wav',providers.speech,
                     [cfg['tts_voice'],cfg['tts_rate'],cfg['language'],cfg['project']])]
        for operation,text,extension,provider,options in operations:
            identity=key([operation,text,options])
            cached=cache/(identity+'.'+extension)
            target=assets/f'scene-{number:03d}.{extension}'
            try:
                with FileLock(str(cache/(identity+'.lock')),timeout=1800):
                    if not cached.is_file():
                        stage(output,f'{operation}:{number}',lambda:provider(text,cached,configured))
                    if not target.is_file():
                        shutil.copy2(cached,target)
            except Exception as error:
                errors.append(f'scene-{number:03d} {operation}: {error}')
        return errors
    with ThreadPoolExecutor(max_workers=max(1,int(cfg.get('workers',2)))) as pool:
        errors=[message for result in pool.map(material,plan.get('scenes',[])) for message in result]
    write(output/'assets.json',{'directory':str(assets),'errors':errors})
    return assets,errors


def build_outputs(plan,assets,output,cfg,mode):
    from .builder import build
    from .render import render
    output=Path(output)
    assets=Path(assets).expanduser().resolve()
    present=[(p.name,p.stat().st_size,p.stat().st_mtime_ns) for p in sorted(assets.glob('scene-*')) if p.is_file()]
    visual_keys={'width','height','fps','font','font_family','caption_color','caption_size','caption_y',
                 'label_color','label_size','label_x','label_y','hook_size','drafts_dir'}
    signature=key({'plan':plan,'files':present,'settings':{k:v for k,v in cfg.items() if k in visual_keys},'mode':mode})[:20]
    folder=output/'builds'/signature
    folder.mkdir(parents=True,exist_ok=True)
    prior=folder/'result.json'
    saved=json.loads(prior.read_text(encoding='utf-8')) if prior.is_file() else {}
    result={'status':'complete','mode':mode,'errors':[]}
    if mode in ('mp4','both'):
        try:
            completed=saved.get('mp4')
            result['mp4']=completed if completed and Path(completed['video']).is_file() else stage(output,'render',lambda:render(plan,assets,folder,cfg))
        except Exception as error:
            result['errors'].append('MP4: '+str(error))
    if mode in ('draft','both'):
        if cfg.get('drafts_dir'):
            try:
                completed=saved.get('draft')
                result['draft']=completed if completed and (Path(completed['draft'])/'draft_content.json').is_file() else stage(output,'draft',lambda:build(plan,assets,cfg['drafts_dir'],cfg))
            except Exception as error:
                result['errors'].append('draft: '+str(error))
        else:
            result['errors'].append('draft: CAPCUT_DRAFTS_DIR が未設定です。素材を保持しています')
    if result['errors'] or any(r.get('omitted') for r in (result.get('draft',{}),result.get('mp4',{}))):
        result['status']='partial'
    write(prior,result)
    return result


def generate(topic,output,cfg,mode='draft',plan_file=None):
    from . import providers
    output=Path(output).expanduser().resolve()
    output.mkdir(parents=True,exist_ok=True,mode=0o700)
    with FileLock(str(output/'job.lock'),timeout=0):
        record(output,'generating',{'topic':topic})
        run={'topic':topic,'mode':mode,'settings':cfg,'plan_ready':False,
             'plan_file':str(Path(plan_file).expanduser().resolve()) if plan_file else None}
        write(output/'run.json',run)
        if plan_file:
            plan=json.loads(Path(plan_file).expanduser().read_text(encoding='utf-8'))
        else:
            identity=key([topic,cfg['gemini_route'],cfg['gemini_model'],cfg['target_seconds'],cfg['scene_goal'],cfg['project'] if cfg['gemini_route']=='vertex' else None])
            cached=home()/'cache'/'plans'/identity
            with FileLock(str(home()/('plan-'+identity+'.lock')),timeout=1800):
                plan=stage(output,'plan',lambda:providers.plan(topic,cached,{**cfg,'usage_dir':str(output)}))
        plan={**plan,'scenes':[{**scene,'scene_number':i} for i,scene in enumerate(plan.get('scenes',[]),1)]}
        write(output/'plan.json',plan)
        write(output/'run.json',{**run,'plan_ready':True})
        if mode=='plan':
            result={'status':'plan_ready','plan':str(output/'plan.json'),'errors':[]}
            write(output/'result.json',result)
            record(output,'plan_ready',result)
            return result
        assets,errors=generate_assets(plan,output,cfg)
        result={'status':'assets_ready','plan':str(output/'plan.json'),'assets':str(assets),'errors':errors}
        if mode!='assets':
            built=build_outputs(plan,assets,output,cfg,mode)
            result.update(built)
            result['errors']=errors+built.get('errors',[])
        if result['errors']:
            result['status']='partial'
        write(output/'result.json',result)
        record(output,result['status'],result)
        return result


def resume(output):
    output=Path(output).expanduser().resolve()
    saved=json.loads((output/'run.json').read_text(encoding='utf-8'))
    cfg=saved['settings']
    cfg['drafts_dir']=os.getenv('CAPCUT_DRAFTS_DIR') or cfg.get('drafts_dir','')
    plan=output/'plan.json'
    source=plan if saved.get('plan_ready',True) and plan.is_file() else saved.get('plan_file')
    return generate(saved['topic'],output,cfg,saved['mode'],source)
