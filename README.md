# Misskey リアクションボット

Misskey リアクションボットは、Misskey のタイムラインを監視し、投稿内容に応じたカスタム絵文字で自動的にリアクションを追加するボットです。このボットは、Gemini API を用いてカスタム絵文字をあらかじめ定義された感情カテゴリに分類し、Misskey の WebSocket ストリーミング API を利用してタイムラインの投稿をリアルタイムに監視します。

## 概要

このボットは主に以下の2つのコンポーネントから構成されています：

- **bot.py**：
  ボット本体。Misskey の WebSocket API に接続し、新しい投稿（ノート）を監視します。投稿が検出されると、その内容を処理し、適したカスタム絵文字リアクションを追加します。また、各処理の状況はログ出力により確認できます。

- **preprocess_emojis.py**：
  Misskey サーバーからカスタム絵文字を取得し、Gemini API を用いてあらかじめ定義された感情カテゴリ（例：happy, sad, love など）に分類します。処理結果は JSON ファイルとして保存され、ボットがリアクションに使用する絵文字の選択に役立ちます。

また、ボットはサンプルの環境変数ファイルも利用します：

- **.env.example**：
  ボットの実行に必要な環境変数のテンプレートです。以下の設定項目が含まれます：
  - Misskey API の設定
    - `MISSKEY_HTTP_HOST`: Misskey サーバーのホスト名（例: misskey.vip）
    - `MISSKEY_WS_HOST`: WebSocket 接続用のホスト名（例: misskey.vip）
    - `MISSKEY_TOKEN`: Misskey API アクセス用のトークン
  - Gemini API の設定
    - `GEMINI_API_KEY`: Google Gemini API の認証キー
    - `GEMINI_MODEL`: 使用する Gemini モデル（推奨: gemini-2.0-flash-lite）
  - ログ設定
    - `LOG_LEVEL`: ログの詳細レベル（INFO, DEBUG, WARNING, ERROR）
    - `MAX_NOTE_TEXT_LENGTH`: ログに表示するノートテキストの最大文字数
  - リアクション動作の設定
    - `REACTION_PROBABILITY`: リアクションする確率（0.0〜1.0）
    - `REACT_TO_REPLIES`: リプライにもリアクションするかどうか（true/false）
    - `REACT_TO_FOLLOWERS`: フォロワー向け投稿にもリアクションするかどうか（true/false）
  - 再試行や WebSocket 再接続の設定（ファイル内の後半部分に詳細あり）

## セットアップ

### 直接実行する場合

1. **リポジトリのクローン**

   ```bash
   git clone git@github.com:lqvp/reaction-bot.git
   cd reaction-bot
   ```

2. **依存パッケージのインストール**

   本ボットは Python 3 が必要です。Python 3 をインストールしたうえで、以下のコマンドで必要なパッケージをインストールしてください。`requirements.txt` がある場合は、以下を実行します：

   ```bash
   pip install -r requirements.txt
   ```

3. **環境変数の設定**

   `.env.example` をコピーして `.env` として保存してください：

   ```bash
   cp .env.example .env
   ```

   その後、`.env` ファイル内の各種設定値をご自身の環境に合わせて更新してください。
   `GEMINI_MODEL`は`gemini-2.0-flash-lite`を推奨します。

### Dockerを使用する場合

1. **リポジトリのクローン**

   ```bash
   git clone git@github.com:lqvp/reaction-bot.git
   cd reaction-bot
   ```

2. **環境変数の設定**

   `.env.example` をコピーして `.env` として保存してください：

   ```bash
   cp .env.example .env
   ```

   その後、`.env` ファイル内の各種設定値をご自身の環境に合わせて更新してください。

3. **Docker Composeを使用してビルド・実行**

   ```bash
   docker-compose up -d
   ```

   これにより、リアクションボットのコンテナがバックグラウンドで起動します。

## ボットの実行方法

### 直接実行する場合

- **ボットの起動**

  `src/main.py` を実行することで、ボットが起動し、Misskey サーバーに接続してタイムラインの監視が開始されます：

  ```bash
  python main.py --mode bot
  ```

  新しい投稿が検出されると、ボットがその内容を処理し、適切なカスタム絵文字リアクションを追加します。

- **絵文字の前処理**

  カスタム絵文字の最新データを取得し、再分類するためには、以下のコマンドを実行してください：

  ```bash
  python main.py --mode preprocess
  ```

  このスクリプトは、Misskey サーバーから最新のカスタム絵文字を取得し、Gemini API を用いて定義済みの感情カテゴリへ分類、`emojis_processed.json` として保存します。

### Dockerを使用する場合

- **ボットの起動**

  Docker Composeを使用してボットを起動します：

  ```bash
  docker-compose up -d
  ```

- **絵文字の前処理**

  カスタム絵文字の前処理を実行するには、以下のコマンドを使用します：

  ```bash
  docker-compose run --rm --profile preprocess preprocess
  ```

  これにより、前処理用のコンテナが一時的に起動し、処理後に自動的に削除されます。

- **ログの確認**

  コンテナのログを確認するには：

  ```bash
  docker-compose logs -f
  ```

- **ボットの停止**

  ```bash
  docker-compose down
  ```

## ログ出力

ボットは、各処理状況をコンソールへのログ出力により表示します。ログレベルは `.env` ファイルの `LOG_LEVEL` 変数で設定可能です（例：DEBUG, INFO, WARNING, ERROR）。

- **INFO**：通常の情報（処理状況や成功メッセージなど）。
- **SUCCESS**：操作成功時の通知。
- **WARNING** / **ERROR**：問題発生時の警告やエラーメッセージ。

## カスタム絵文字の分類

`preprocess_emojis.py` では、取得したカスタム絵文字を、以下のような感情カテゴリに分類しています：

- happy
- sad
- love
- angry
- surprised
- thinking
- fun
- food
- agreement
- disagreement
- celebration
- greeting
- sleep
- animal
- cute
- cool
- music
- work
- weather
- tech
- gaming
- sports
- nature

Gemini API を利用して、絵文字名や元のカテゴリ情報をもとに最適な分類を行い、定義されたカテゴリに合わないものは `other` として分類されます。

## コントリビュート（貢献）

このリポジトリに貢献したい場合は、自由にフォークしてプルリクエストを送ってください。大きな変更を提案する場合は、最初に Issue を立てて議論することを推奨します。

## ライセンス

[MIT](LICENSE)
