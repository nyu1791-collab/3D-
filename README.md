# 3D図解解説 — 3D-

テーマから **台本 → 断面図画像 → ナレーション → 字幕・ラベル・ズーム演出 → CapCutドラフト／MP4** を作る独立アプリです。他の制作リポジトリのコード・Python環境・DBは不要で、ClipForge本体は変更しません。

静止画にキーフレームを付けた立体風の図解です。実際の立体モデルや水の物理シミュレーションを生成するものではありません。30秒・5シーンは目安で、不足による停止・水増し・自動再生成はありません。

## まず、クラウドを使わずデモを作る

Python 3.11以降、FFmpeg/FFprobeが必要です。MP4出力には字幕描画対応のFFmpegを使ってください。

```powershell
git clone https://github.com/nyu1791-collab/3D-.git
cd 3D-
py -3 -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python main.py demo --output C:/work/3d-demo --mode mp4
```

「雨水が地下水になるまで」の自作模式図5枚、字幕、ラベル、ズーム／パンを含む約30秒の縦動画を作ります。**デモの音声は無音の尺合わせ素材です。Googleの画像生成・音声合成・課金APIは呼びません。** 既存のデモ素材は再利用します。

出力した `result.json` にMP4の保存場所を記録し、端末にも表示します。

![自作模式図を使った縦動画デモの一場面](docs/demo-preview.png)

## CapCutドラフトも作る

```powershell
.\.venv\Scripts\python -m pip install -r requirements-capcut.txt
.\.venv\Scripts\python main.py demo --output C:/work/3d-demo --mode both --drafts-dir "C:/実際のCapCutドラフト保存先"
```

CapCutの設定画面に出るドラフト保存先を使ってください。画像・音声・編集可能な字幕・ラベル・ズームのタイムラインを、新しい名前で作成します。利用した素材もドラフト内へコピーし、既存のプロジェクトや元素材を上書きしません。CapCutで開いて調整し、最終書き出しはアプリから行います。別PCへドラフトを移す場合は、そのPC上で生成するか素材参照を再設定してください。

## Google接続を使う制作

```powershell
.\.venv\Scripts\python -m pip install --upgrade -r requirements-google.txt
Copy-Item .env.example .env
```

CapCutドラフトを出す `draft` / `both` では、上の `requirements-capcut.txt` もインストールしてください。`mp4` はCapCutなしで出力できます。

`.env` に自分のAI Studioキー、使用するCloudプロジェクト、CapCutドラフト保存先を設定します。APIキーはGitへ入れません。Cloud側は既存のADCまたはWIFを使い、サービスアカウントの長期JSON秘密鍵は新規発行しません。

```powershell
gcloud auth application-default login
gcloud auth application-default set-quota-project project-fdadb4dd-cb77-4270-9cd
```

Cloud側で使うAPI・請求先・権限の準備は [Googleの接続と料金](docs/GOOGLE.md) を参照してください。このアプリはAPIの有効化や権限付与を勝手に行いません。

設定の既定値は次のとおりです。

| 工程 | 経路・モデル |
|---|---|
| 台本とシーン分割 | AI Studio / `gemini-3.8-flash` |
| 断面図画像 | Cloud / `gemini-2.5-flash-image` |
| ナレーション | Cloud Text-to-Speech / `ja-JP-Neural2-C` |
| タイムライン | pyCapCut 0.0.4 またはローカルFFmpeg |

ユーザー案の旧Imagenモデルと旧Vertex SDKは、公式の退役情報に合わせて既定実装から外しました。画像方式・モデルは設定で明示できますが、失敗時に別モデルへ暗黙で切り替えません。[参考元と整合性](docs/SOURCES.md)

### 台本だけ作る

```powershell
.\.venv\Scripts\python main.py generate "家の断熱材が熱の移動を抑える仕組み" --output C:/work/insulation --mode plan
```

これは台本の要求だけです。画像と音声はまだ生成しません。`plan.json` のナレーション、シーン、画像プロンプト、ラベル、動きを編集できます。

### 素材と動画を作る

```powershell
# 素材だけ
.\.venv\Scripts\python main.py generate "家の断熱材が熱の移動を抑える仕組み" --output C:/work/insulation --mode assets
# 画像・音声からドラフトまで
.\.venv\Scripts\python main.py generate "家の断熱材が熱の移動を抑える仕組み" --output C:/work/insulation --mode draft
# MP4とドラフトの両方
.\.venv\Scripts\python main.py generate "家の断熱材が熱の移動を抑える仕組み" --output C:/work/insulation --mode both
```

同じテーマ・設定なら、成功済みの台本、画像、音声を再利用します。自分で編集した台本を使うときは `--plan C:/work/insulation/plan.json` を指定してください。編集したナレーションや画像プロンプトなど、入力が変わった素材だけを新しく生成します。

自分の設定は `config/default.yaml` をもとに `config/local.yaml` に保存し、次のように指定します。

```powershell
.\.venv\Scripts\python main.py --config config/local.yaml generate "テーマ" --output C:/work/new-job --mode both
```

字幕・ラベルの色、大きさ、位置もこの設定で変更できます。位置は画面中心が0、右・上が＋1、左・下が−1です。ラベルは台本のシーンごとの指定を優先します。

## 保存済み素材から作る・途中を続行する

```powershell
.\.venv\Scripts\python main.py resume C:/work/insulation
.\.venv\Scripts\python main.py jobs
.\.venv\Scripts\python main.py build --plan C:/work/plan.json --assets C:/work/assets --output C:/work/local-build --mode mp4
```

既存素材は `scene-001.png` と `scene-001.wav` の組で用意します。シーン番号は台本の `scene_number` に対応します。画像と音声がそろっていないシーンは理由を残し、そろったシーンを使います。取得済みの素材や以前の出力は保持します。

台本の取得中に通信が止まった場合も `resume` で続行できます。同じ素材・設定でMP4かドラフトの片方が完成していれば、それを再利用し、未完了の出力だけを進めます。

作業記録は既定で `~/.3d-explainer/pipeline.sqlite3`、成功済み素材のキャッシュもそのフォルダに保存します。`EXPLAINER_DATA_DIR` で変更できます。ジョブの `request-usage.jsonl` にはモデル、経路、使用量、試行回数を記録し、APIキーやトークンは記録しません。

## 複数テーマを進める

```powershell
.\.venv\Scripts\python main.py batch config/batch.example.yaml --workers 1
```

サンプルは台本のみの `mode: plan` です。画像・音声も生成するときは各項目のmodeを変更してください。テーマ間の並列数と、テーマ内の素材生成並列数（設定の `workers`、既定2）は別です。

## 料金・字幕・表現

- AI Studioの無料枠はモデル・ティア・利用状況によって条件が異なります。Cloud画像生成やTTSの無料枠・クレジット適用も、請求先の実際の条件によります。「完全無料」「クレジット消費ゼロ」とは自動判定しません。
- 画像を動かす疑似3Dです。スクリーンショットのような写実的な見た目は、画像モデル・プロンプト・素材に依存します。
- 字幕はナレーション音声の実尺に合わせます。取得していない単語時刻を作って、単語カラオケができたとは扱いません。
- 目標の尺・シーン数・演出量は停止条件にしません。品質監査、追加査読モデル、完成映像の検査工程は追加していません。

構成は [設計](docs/DESIGN.md)、Google接続は [接続と料金](docs/GOOGLE.md)、公開リポジトリから取り入れた範囲は [参考元](docs/SOURCES.md) にあります。

自作素材でMP4とCapCutドラフトを出力しました。Googleの実生成、無料枠・クレジット適用、Windows版CapCutでの表示は未実施です。
