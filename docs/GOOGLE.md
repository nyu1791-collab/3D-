# Googleの接続と料金の扱い

## 台本と素材の経路を明示する

台本は `gemini_route: aistudio` の場合だけ `GEMINI_API_KEY` を使います。`gemini_route: vertex` は自分のGoogle Cloud ADC認証を使います。画像はCloud側の画像モデル、ナレーションはCloud Text-to-Speechを使用します。失敗時に別キーや別モデルへ自動で切り替えません。

設定するプロジェクトの例は `project-fdadb4dd-cb77-4270-9cd` です。この値が設定されているだけで、権限・クレジット残高・課金なしが確認できたことにはしません。

```powershell
# Google Cloud CLIで、このPC用のADCを用意します。
gcloud auth application-default login
gcloud auth application-default set-quota-project project-fdadb4dd-cb77-4270-9cd
```

Cloudの画像生成とText-to-Speechには、それぞれ利用するAPIの有効化・請求先の設定・必要な操作権限が必要です。アプリからAPIを勝手に有効化したり、サービスアカウントの長期JSON秘密鍵を発行したりはしません。既存のADCまたはWIFを使います。

## 現在のモデルとSDK

提示案の `imagen-3.0-generate-002` は、公式のCloudモデルライフサイクル表では2026年6月30日退役です。Imagen 4の掲載モデルも同日退役として扱われ、公式表は `gemini-2.5-flash-image` を移行先に示しています。したがって既定の画像方式は `image_backend: gemini`、モデルは `image_model: gemini-2.5-flash-image` とします。自動フォールバックではなく、構成上の明示的な選択です。[公式モデルライフサイクル](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/model-versions)

`image_backend: imagen` を明示した場合は、設定したモデルに `generate_images` を呼びます。退役したモデルが成功することを保証するものではありません。画像出力がない場合も、別モデルへ勝手に再要求しません。通常の安全フィルターを維持します。

現行Google Gen AI SDKはCloud接続の `enterprise=True` と、旧名の `vertexai=True` を受け付けます。既定は互換性のある `cloud_client: vertex`（SDK引数 `vertexai=True`）です。導入したSDKに合わせ、`cloud_client: enterprise` も明示できます。SDKの引数エラー後に暗黙で接続方式を変えません。旧 `vertexai.preview.vision_models` は使いません。[公式SDK](https://googleapis.github.io/python-genai/) / [公式Clientソース](https://github.com/googleapis/python-genai/blob/main/google/genai/client.py)

台本の既定モデルは `gemini-3.8-flash` です。提示案の2.5 Flashについては、Developer APIとCloudのモデル提供状況を同一視しません。希望のモデルは `gemini_model` で明示してください。

## 無料枠・クレジット

AI Studio側にはモデル・ティアごとの無料枠があります。現在の価格表にはGemini 3.8 FlashのStandard Free Tierが掲載されていますが、同じモデルでも課金設定・利用枠・利用可能な機能は接続するプロジェクトと経路に依存します。AI Studioを使うことだけから「完全無料」とは判定しません。[Gemini Developer APIの公式料金](https://ai.google.dev/gemini-api/docs/pricing)

Cloud TTSの価格表にはNeural2の月100万文字までの無料使用枠があります。請求先の有効化が必要で、同じ枠の他の使用分や、無料枠超過分を含めて請求されます。別カテゴリの音声では条件が異なります。既定音声 `ja-JP-Neural2-C` の提供状況は公式音声一覧で確認できますが、この環境での呼び出し実績を示すものではありません。[Cloud TTS料金](https://cloud.google.com/text-to-speech/pricing) / [対応音声](https://docs.cloud.google.com/text-to-speech/docs/list-voices-and-types)

画像生成の料金、トライアルクレジットの適用・残高・有効期限はGoogle Cloudの請求画面で確認してください。このプログラムはクレジットを自動申請せず、残高も推測しません。[Google Cloud無料プログラム](https://cloud.google.com/free/docs/free-cloud-features)

## 記録と再開

完成済みの台本・画像・音声があれば再利用します。各要求について、経路、プロジェクト、モデル、試行回数、成否、所要時間、取得できた使用量を `request-usage.jsonl` に記録します。音声では要求文字数、画像では要求枚数を記録します。原文・画像プロンプトやAPIキー・トークンは使用量ログに書きません。

SDK内の重複再試行を無効にし、一時的な429・500・502・503・504と通信障害だけを合計3回まで再試行します。認証・権限・モデル名のエラーは同じ要求を繰り返しません。キーのローテーションでレート制限を回避する仕組みはありません。

この実装作業では、課金API・画像モデル・Cloud TTSは起動していません。生成物があることと、Cloud接続・無料枠・クレジット適用の成功は別に扱います。

この実装では `google-genai==2.34.0` を指定しています。明示したCloudの認証情報は環境のAI Studioキーより優先されるSDK仕様を使い、並列処理中に環境変数を削除・差し替える方法は使いません。
