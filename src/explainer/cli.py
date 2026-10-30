import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import yaml
from . import pipeline


def main():
    parser=argparse.ArgumentParser(description='独立した図解解説動画制作。尺・シーン数は目安です。')
    parser.add_argument('--config',type=Path)
    sub=parser.add_subparsers(dest='action',required=True)
    create=sub.add_parser('generate',help='台本・画像・音声を生成し、動画やドラフトにする')
    create.add_argument('topic')
    create.add_argument('--output',required=True,type=Path)
    create.add_argument('--mode',choices=['plan','assets','draft','mp4','both'],default='draft')
    create.add_argument('--plan',type=Path,help='自分で用意した台本JSONを使う')
    build=sub.add_parser('build',help='既存素材から出力。クラウド生成なし')
    build.add_argument('--plan',required=True,type=Path)
    build.add_argument('--assets',required=True,type=Path)
    build.add_argument('--output',required=True,type=Path)
    build.add_argument('--mode',choices=['draft','mp4','both'],default='draft')
    build.add_argument('--drafts-dir',type=Path)
    demo=sub.add_parser('demo',help='自作模式図と無音素材で作る、クラウド不使用のデモ')
    demo.add_argument('--output',required=True,type=Path)
    demo.add_argument('--mode',choices=['assets','draft','mp4','both'],default='mp4')
    demo.add_argument('--drafts-dir',type=Path)
    resume=sub.add_parser('resume',help='成功済み応答・素材を再利用して続行')
    resume.add_argument('output',type=Path)
    sub.add_parser('jobs',help='自分の制作記録')
    batch=sub.add_parser('batch',help='複数テーマを個別に保存して制作')
    batch.add_argument('file',type=Path)
    batch.add_argument('--workers',type=int,default=1)
    args=parser.parse_args()
    cfg=pipeline.settings(args.config)
    try:
        if args.action=='generate':
            result=pipeline.generate(args.topic,args.output,cfg,args.mode,args.plan)
        elif args.action=='resume':
            result=pipeline.resume(args.output)
        elif args.action=='jobs':
            with pipeline.connect() as db:
                result=[dict(row) for row in db.execute('SELECT output,status,updated FROM jobs ORDER BY updated DESC')]
        elif args.action=='batch':
            entries=yaml.safe_load(args.file.read_text(encoding='utf-8'))['jobs']
            def produce(item):
                try:
                    return pipeline.generate(item['topic'],item['output'],cfg,item.get('mode','draft'),item.get('plan'))
                except Exception as error:
                    output=item.get('output') if isinstance(item,dict) else None
                    if output:
                        pipeline.record(Path(output).expanduser().resolve(),'failed',{'reason':str(error)})
                    return {'status':'failed','output':output,'errors':[str(error)]}
            with ThreadPoolExecutor(max_workers=max(1,args.workers)) as pool:
                results=list(pool.map(produce,entries))
            result={'jobs':results,'errors':[message for row in results for message in row.get('errors',[])]}
        else:
            if getattr(args,'drafts_dir',None):
                cfg['drafts_dir']=str(args.drafts_dir.expanduser().resolve())
            if args.action=='demo':
                from .demo import create
                plan,assets=create(args.output)
            else:
                plan=json.loads(args.plan.read_text(encoding='utf-8'))
                assets=args.assets
            source=args.output/'plan.json' if args.action=='demo' else args.plan
            result={'status':'assets_ready','plan':str(source.expanduser().resolve()),'assets':str(Path(assets).expanduser().resolve()),'demo':args.action=='demo'}
            if args.mode!='assets':
                result.update(pipeline.build_outputs(plan,assets,args.output,cfg,args.mode))
            pipeline.write(args.output/'result.json',result)
            pipeline.record(args.output,result['status'],result)
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return 1 if isinstance(result,dict) and result.get('errors') else 0
    except Exception as error:
        if getattr(args,'output',None):
            pipeline.record(args.output,'failed',{'reason':str(error)})
        parser.exit(1,f'制作を完了できませんでした: {error}\n')


if __name__=='__main__':
    raise SystemExit(main())
