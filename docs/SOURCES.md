# 参考元と整合性

2026年10月30日時点で参照した公開資料です。料金表やモデルの提供期間は変わるため、実行先のモデル名・経路を設定に残します。APIを呼べたことから無料枠やクレジット残高を推測しません。

## Googleのモデル・料金・接続

| 資料 | この実装に反映したこと |
|---|---|
| [Gemini APIの料金](https://ai.google.dev/gemini-api/docs/pricing) / [課金と利用階層](https://ai.google.dev/gemini-api/docs/billing) | 無料枠は対象モデルと利用階層・制限に依存。AI Studioで使うキーが常に無料とは扱わない。現在の3.8 Flash Standardには無料枠の記載があるが、本アカウントへの適用を確認したものではない |
| [Gemini Developer APIのモデル終了情報](https://ai.google.dev/gemini-api/docs/deprecations) | 2.5 Flashは既存利用者向けの扱いがあり、新規プロジェクトには3.5 Flash-Liteまたは3.8 Flashが案内されている。台本モデルを古いサンプルに固定しない |
| [Google Cloudのモデル期間](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/model-versions) | 提案にあった `imagen-3.0-generate-002` は2026年6月30日終了の一覧にある。画像生成の既定を提供中のGemini画像モデルへ移し、Imagenを指定した実行と混同しない。Vertexの2.5 Flashは2026年10月20日終了で、Developer API側の扱いとは別 |
| [Vertex AI SDK移行案内](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/deprecations/genai-vertexai-sdk) / [Google Gen AI SDK](https://googleapis.github.io/python-genai/) | 旧 `vertexai.vision_models` などの生成AIモジュールは2026年6月24日以降のSDKから除かれる案内がある。`google-genai` を使い、画像の `generate_content` とImagen用の `generate_images` を区別する |
| [Cloud Text-to-Speech料金](https://cloud.google.com/text-to-speech/pricing) | Neural2の表には月100万文字までの無料利用量がある。音声種別で条件が異なり、上限超過・他サービスの利用まで0円とはしない |
| [音声一覧](https://docs.cloud.google.com/text-to-speech/docs/list-voices-and-types) | `ja-JP-Neural2-C` は公式一覧上で日本語の男性音声。これは本環境での合成成功や音質の実機確認とは別 |
| [ADC認証](https://docs.cloud.google.com/docs/authentication/provide-credentials-adc) / [Google Cloud無料プログラム](https://docs.cloud.google.com/free/docs/free-cloud-features) | ローカルADCや実行環境の認証を使用。新しい長期サービスアカウント鍵を発行する設計にしない。クレジットの有無・適用先・有効期限はアカウントの請求情報で扱う |

画像は `image_backend` と `image_model` で明示します。提供終了モデルの要求が失敗したとき、別モデルへ黙って切り替えて成功扱いにはしません。安全設定の弱化や、レート制限を回避するためのキー切り替えも追加しません。

## 公開リポジトリ

| 参考元 | 採用範囲 |
|---|---|
| [GuanYixuan/pyCapCut 0.0.4](https://github.com/GuanYixuan/pyCapCut/tree/0.0.4) | 外部ライブラリとして使用。動画・音声・テキストのトラック、キーフレーム、ドラフト保存。旧 `pyJianYingDraft` のクラス名を混ぜない |
| [harry0703/MoneyPrinterTurbo](https://github.com/harry0703/MoneyPrinterTurbo) | テーマから台本・シーン・素材指示へ分ける設計を参考。アプリ全体やスポンサー・画像素材を複製しない |
| [aaurelions/short-video-maker](https://github.com/aaurelions/short-video-maker) | SQLiteで依頼・工程・再開を分ける考え方を参考。APIキーローテーションや監査機能は取り込まない |
| [WyattBlue/auto-editor](https://github.com/WyattBlue/auto-editor) / [SYSTRAN/faster-whisper](https://github.com/SYSTRAN/faster-whisper) / [ClipsAI/clipsai](https://github.com/ClipsAI/clipsai) | 切り抜き・無音削除・認識・顔中心のリフレーム向け。図解画像と既知のナレーションを組む本アプリの必須依存にはしない |

pyCapCutの公開案内では、生成したドラフトをWindows版CapCutで開き、完成動画はアプリから書き出します。ドラフトJSONが生成できたことと、最新版CapCut Proで全素材・全エフェクトを使えたことは区別します。

## コピーしたコード

`src/explainer/render.py` のBT.709変換とタグ付けのフィルタ文字列は、[MoneyPrinterTurbo](https://github.com/harry0703/MoneyPrinterTurbo) のコミット `90f7701` の `app/services/video.py` から取り、zoompanの前に変換するよう変更して使っています。

```text
MIT License

Copyright (c) 2024 Harry

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
