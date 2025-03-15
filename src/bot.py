import os
from dotenv import load_dotenv
import json
import aiohttp
import asyncio
import websockets
import google.generativeai as genai
import re
import random
import time
from datetime import datetime
from src.preprocess_emojis import EMOTION_CATEGORIES

# 環境変数のロード
load_dotenv("config/.env")

# Misskey API設定
MISSKEY_HTTP_HOST = os.getenv("MISSKEY_HTTP_HOST")
MISSKEY_WS_HOST = os.getenv("MISSKEY_WS_HOST")
MISSKEY_TOKEN = os.getenv("MISSKEY_TOKEN")

# API設定
API_PROTOCOL = (
    "https"
    if os.getenv("API_SECURE", "true").lower() in ["true", "1", "yes"]
    else "http"
)
MISSKEY_API_URL = f"{API_PROTOCOL}://{MISSKEY_HTTP_HOST}/api"

# WebSocket設定
WS_SECURE = os.getenv("WS_SECURE", "true").lower() in ["true", "1", "yes"]
WS_PROTOCOL = "wss" if WS_SECURE else "ws"
MISSKEY_WS_URL = f"{WS_PROTOCOL}://{MISSKEY_WS_HOST}/streaming?i={MISSKEY_TOKEN}"

# ロギング設定
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
MAX_NOTE_TEXT_LENGTH = int(os.getenv("MAX_NOTE_TEXT_LENGTH", "50"))

# リアクション設定
REACTION_PROBABILITY = float(os.getenv("REACTION_PROBABILITY", "1.0"))

# リプライやリノートにもリアクションするかどうか（デフォルトはfalse）
REACT_TO_REPLIES = os.getenv("REACT_TO_REPLIES", "false").lower() in [
    "true",
    "1",
    "yes",
]

# フォロワー向け投稿にもリアクションするかどうか（デフォルトはfalse）
REACT_TO_FOLLOWERS = os.getenv("REACT_TO_FOLLOWERS", "false").lower() in [
    "true",
    "1",
    "yes",
]

# Gemini API設定
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash-lite")

# 再試行設定
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))
RETRY_DELAY = int(os.getenv("RETRY_DELAY", "2"))

# WebSocket再接続設定
WS_RECONNECT_DELAY_INITIAL = int(os.getenv("WS_RECONNECT_DELAY_INITIAL", "5"))
WS_RECONNECT_DELAY_MAX = int(os.getenv("WS_RECONNECT_DELAY_MAX", "60"))
WS_RECONNECT_FACTOR = float(os.getenv("WS_RECONNECT_FACTOR", "1.5"))

# WebSocketのUser-Agent設定
WS_USER_AGENT = os.getenv("WS_USER_AGENT", "MisskeyReactionBot/1.0")


# コンソール出力のカラー設定
class Colors:
    HEADER = "\033[95m"
    BLUE = "\033[94m"
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    ENDC = "\033[0m"
    BOLD = "\033[1m"
    UNDERLINE = "\033[4m"


def should_log(level):
    """指定されたログレベルが現在の設定で表示すべきかを判断"""
    levels = {"DEBUG": 0, "INFO": 1, "WARNING": 2, "ERROR": 3}
    current_level = levels.get(LOG_LEVEL, 1)  # デフォルトはINFO
    log_level = levels.get(level, 1)
    return log_level >= current_level


# ロギング関数
def log_info(message):
    if not should_log("INFO"):
        return
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(
        f"{Colors.BLUE}[INFO]{Colors.ENDC} {Colors.BOLD}[{timestamp}]{Colors.ENDC} {message}"
    )


def log_success(message):
    if not should_log("INFO"):  # SUCCESSはINFOと同レベル
        return
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(
        f"{Colors.GREEN}[SUCCESS]{Colors.ENDC} {Colors.BOLD}[{timestamp}]{Colors.ENDC} {message}"
    )


def log_warning(message):
    if not should_log("WARNING"):
        return
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(
        f"{Colors.YELLOW}[WARNING]{Colors.ENDC} {Colors.BOLD}[{timestamp}]{Colors.ENDC} {message}"
    )


def log_error(message):
    if not should_log("ERROR"):
        return
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(
        f"{Colors.RED}[ERROR]{Colors.ENDC} {Colors.BOLD}[{timestamp}]{Colors.ENDC} {message}"
    )


def log_reaction(username, note_text, reaction):
    if not should_log("INFO"):  # REACTIONはINFOと同レベル
        return
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # テキストを短く切り詰める
    short_text = (
        note_text[:MAX_NOTE_TEXT_LENGTH] + "..."
        if len(note_text) > MAX_NOTE_TEXT_LENGTH
        else note_text
    )
    short_text = short_text.replace("\n", " ")
    print(
        f'{Colors.CYAN}[REACTION]{Colors.ENDC} {Colors.BOLD}[{timestamp}]{Colors.ENDC} {Colors.YELLOW}@{username}{Colors.ENDC}: "{short_text}" → {Colors.GREEN}{reaction}{Colors.ENDC}'
    )


def log_ws(message):
    """WebSocketイベントのログ専用関数"""
    if not should_log("INFO"):
        return
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(
        f"{Colors.BLUE}[WEBSOCKET]{Colors.ENDC} {Colors.BOLD}[{timestamp}]{Colors.ENDC} {message}"
    )


# Gemini APIの設定
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel(GEMINI_MODEL)

BOT_USER_ID = None
# 有効な絵文字名のセット（高速検索用）
VALID_EMOJI_NAMES = set()


# カスタム絵文字データのロード
def load_emoji_data():
    """前処理済みの絵文字データをロードする"""
    global VALID_EMOJI_NAMES

    for retry in range(MAX_RETRIES):
        try:
            with open("data/emojis_processed.json", "r", encoding="utf-8") as f:
                emoji_data = json.load(f)

            # 有効な絵文字名のセットを作成
            VALID_EMOJI_NAMES.clear()
            for category in emoji_data["categorized_emojis"]:
                for emoji in emoji_data["categorized_emojis"][category]:
                    VALID_EMOJI_NAMES.add(emoji["name"])

            log_info(
                f"カスタム絵文字データをロードしました: {len(emoji_data['categories'])}カテゴリ, {len(VALID_EMOJI_NAMES)}個の絵文字"
            )
            return emoji_data
        except (FileNotFoundError, json.JSONDecodeError) as e:
            log_error(
                f"カスタム絵文字データの読み込みに失敗しました ({retry + 1}/{MAX_RETRIES}): {type(e).__name__}: {e}"
            )
            if retry < MAX_RETRIES - 1:
                wait_time = RETRY_DELAY * (retry + 1)
                log_warning(f"{wait_time}秒後に再試行します...")
                time.sleep(wait_time)
            else:
                log_warning(
                    "src/preprocess_emojis.pyを実行して、絵文字データを生成してください。"
                )
                return None


# 絵文字データをロード
EMOJI_DATA = load_emoji_data()


def create_prompt_for_reaction(note_text, emoji_examples):
    """リアクション生成用のプロンプトを作成する"""
    return f"""
    以下のノートに対して、文脈に最も適したMisskeyカスタム絵文字を1つ提案してください。

    ルール:
    1. ノートの感情、トーン、内容に合わせて最適なカスタム絵文字を選ぶこと
    2. 単調にならないよう、多様な絵文字を使用すること
    3. 返答は必ず `:emoji_name:` 形式のカスタム絵文字のリストとすること
    4. 通常の Unicode 絵文字 (例: 😊 👍) は使わないでください
    5. カスタム絵文字の名前は必ず有効な名前を指定すること
    6. カスタム絵文字は必ず一個だけ返してください

    利用可能なカスタム絵文字のカテゴリーと例:
    {chr(10).join(emoji_examples)}

    出力は以下のJSON形式で返してください：
    {{"reactions": ":emoji_name:"}}

    ノート: "{note_text}"
    """


def extract_emoji_from_response(response_text):
    """Geminiからのレスポンスからカスタム絵文字を抽出する"""
    # マークダウンコードブロックを処理（```json ... ``` の形式）
    code_block_pattern = r"```(?:json)?\s*(.*?)\s*```"
    code_block_match = re.search(code_block_pattern, response_text, re.DOTALL)
    if code_block_match:
        log_info(f"マークダウンコードブロック検出: {code_block_match.group(1)}")
        json_text = code_block_match.group(1).strip()
    else:
        json_text = response_text.strip()

    # 直接JSONとして解析を試みる
    try:
        response_json = json.loads(json_text)
        reactions = response_json.get("reactions", None)
        if reactions:
            # 文字列の場合
            if isinstance(reactions, str):
                reaction = reactions
                if is_valid_custom_emoji(reaction):
                    return reaction
            # リストの場合
            elif isinstance(reactions, list) and len(reactions) > 0:
                # 有効な絵文字を選択
                for reaction in reactions:
                    if is_valid_custom_emoji(reaction):
                        return reaction
    except (json.JSONDecodeError, KeyError) as e:
        log_warning(f"JSON解析エラー: {type(e).__name__}: {e}")

    # テキストから絵文字名を正規表現で抽出
    emoji_matches = re.findall(r":([\w\d_-]+):", response_text)
    for emoji_name in emoji_matches:
        reaction = f":{emoji_name}:"
        if is_valid_custom_emoji(reaction):
            return reaction

    # どちらの方法でも抽出できない場合はNoneを返す
    return None


async def generate_reaction_with_custom_emojis(note_text):
    """Gemini APIを使ってカスタム絵文字のリアクションを生成（非同期）"""
    # 絵文字データが読み込めない場合はデフォルトでユニコード絵文字を返す
    if not EMOJI_DATA:
        return await generate_reaction_fallback(note_text)

    # 感情カテゴリ毎の例を作成
    emoji_examples = []

    # 各感情カテゴリ（EMOTION_CATEGORIESから取得）から最大5個の絵文字を選択
    for category in EMOTION_CATEGORIES.keys():
        emojis = EMOJI_DATA["categorized_emojis"].get(category, [])
        if emojis:
            sample_size = min(5, len(emojis))
            example_emojis = random.sample(emojis, sample_size)
            example_text = ", ".join([f":{e['name']}:" for e in example_emojis])
            emoji_examples.append(f"- {category} (例: {example_text})")

    # プロンプトを作成
    prompt = create_prompt_for_reaction(note_text, emoji_examples)

    # 複数回試行
    for retry in range(MAX_RETRIES):
        try:
            result = await model.generate_content_async(prompt)
            response_text = result.text.strip()
            log_info(f"Geminiによるリアクション生成: {response_text}")

            # レスポンスから絵文字を抽出
            reaction = extract_emoji_from_response(response_text)

            if reaction:
                log_success(f"リアクションを抽出: {reaction}")
                return reaction
            else:
                log_warning(f"抽出失敗、再試行 ({retry + 1}/{MAX_RETRIES})")
                if retry == MAX_RETRIES - 1:
                    reaction = get_random_emoji()
                    log_warning(f"最終的にランダムリアクションを使用: {reaction}")
                    return reaction
        except Exception as e:
            log_error(
                f"リアクション生成エラー ({retry + 1}/{MAX_RETRIES}): {type(e).__name__}: {e}"
            )
            if retry == MAX_RETRIES - 1:
                reaction = get_random_emoji()
                log_warning(f"エラーによりランダムリアクションを使用: {reaction}")
                return reaction
            await asyncio.sleep(RETRY_DELAY * (retry + 1))


def get_random_emoji():
    """ランダムなカスタム絵文字を取得"""
    if not EMOJI_DATA:
        return "👍"  # データがない場合はデフォルトの絵文字

    # ランダムなカテゴリを選択、感情系が優先的に選ばれるように
    random_category = random.choice(list(EMOTION_CATEGORIES.keys()))

    # 選択したカテゴリに絵文字がない場合は別のカテゴリを試す
    if not EMOJI_DATA["categorized_emojis"].get(random_category):
        for cat in EMOTION_CATEGORIES.keys():
            if EMOJI_DATA["categorized_emojis"].get(cat):
                random_category = cat
                break

    # カテゴリから1つランダムに選択
    emojis = EMOJI_DATA["categorized_emojis"].get(random_category, [])
    if emojis:
        random_emoji = random.choice(emojis)
        return f":{random_emoji['name']}:"

    return "👍"  # どうしても見つからない場合はデフォルト


def is_valid_custom_emoji(emoji_code):
    """カスタム絵文字が有効かチェック"""
    if not EMOJI_DATA or not VALID_EMOJI_NAMES:
        return False

    # :emoji_name: 形式から名前部分だけを抽出
    match = re.match(r"^:([^:]+):$", emoji_code)
    if not match:
        return False

    emoji_name = match.group(1)

    # セットを使用して高速に確認
    return emoji_name in VALID_EMOJI_NAMES


async def generate_reaction_fallback(note_text):
    """フォールバック: ユニコード絵文字を生成（非同期）"""
    prompt = f"""
    以下のノートに対して、文脈に最も適したリアクション絵文字を1つだけ選んでください。

    ルール:
    1. ノートの感情、トーン、内容に合わせて最適な絵文字を選ぶこと
    2. 単調にならないよう、多様な絵文字を使用すること
    3. 「👍」は、他に適切な絵文字がない場合の最終手段としてのみ使用すること
    4. 単語やフレーズではなく、必ず1つの絵文字だけを返すこと

    推奨絵文字の例（状況に応じて選択する必要があるが、これらの絵文字を必ず使用することは必要ありません）:
    - 楽しい内容: 😄 😊 🎉 🥳
    - 悲しい内容: 😢 😭 🥺 💔
    - 驚き: 😲 😮 😱 🤯
    - 質問/疑問: 🤔 ❓ 🧐
    - 怒り/不満: 😠 😡 👿
    - 愛/好意: ❤️ 💕 💖
    - 自然/食べ物: 🌸 🌈 🍜 🍣
    - 同意/支持: 👍 ✅ 💯
    - 応援: 📣 🙌 💪

    出力は以下のJSON形式で返してください：
    {{"reaction": "絵文字"}}

    ノート: "{note_text}"
    """

    for retry in range(MAX_RETRIES):
        try:
            result = await model.generate_content_async(prompt)
            response_text = result.text.strip()
            log_info(f"フォールバックリアクション生成: {response_text}")

            try:
                response_json = json.loads(response_text)
                reaction = response_json["reaction"]
                return reaction
            except (json.JSONDecodeError, KeyError) as e:
                log_warning(
                    f"JSONデコードエラー ({retry + 1}/{MAX_RETRIES}): {type(e).__name__}: {e}"
                )
                # 単純な絵文字の抽出を試みる
                emoji_match = re.search(
                    r'["\']([\p{Emoji}]+)["\']', response_text, re.UNICODE
                )
                if emoji_match:
                    return emoji_match.group(1)

                if retry == MAX_RETRIES - 1:
                    return "👍"  # 最終的なフォールバック
        except Exception as e:
            log_error(
                f"フォールバックリアクション生成エラー ({retry + 1}/{MAX_RETRIES}): {type(e).__name__}: {e}"
            )
            if retry == MAX_RETRIES - 1:
                return "👍"  # 最終的なフォールバック
            await asyncio.sleep(RETRY_DELAY * (retry + 1))


async def add_reaction(note_id, reaction):
    """ノートにリアクションを付与する"""
    url = f"{MISSKEY_API_URL}/notes/reactions/create"
    headers = {"Content-Type": "application/json"}
    data = {"i": MISSKEY_TOKEN, "noteId": note_id, "reaction": reaction}

    for retry in range(MAX_RETRIES):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers, json=data) as response:
                    result = await response.text()
                    if response.status == 200 or response.status == 204:
                        log_success(
                            f"ノート {note_id} にリアクション {reaction} を付与しました"
                        )
                        return True
                    else:
                        log_error(
                            f"リアクション付与エラー ({retry + 1}/{MAX_RETRIES}): ステータス {response.status}, レスポンス: {result}"
                        )
                        if retry == MAX_RETRIES - 1:
                            return False
        except Exception as e:
            log_error(
                f"リアクションAPI接続エラー ({retry + 1}/{MAX_RETRIES}): {type(e).__name__}: {e}"
            )
            if retry == MAX_RETRIES - 1:
                return False

        # 次回のリトライまで待機
        await asyncio.sleep(RETRY_DELAY * (retry + 1))

    return False


async def get_account_info():
    """Misskey APIを使ってアカウント情報を取得（/api/i エンドポイント）"""
    url = f"{MISSKEY_API_URL}/i"
    headers = {"Content-Type": "application/json"}
    data = {"i": MISSKEY_TOKEN}

    for retry in range(MAX_RETRIES):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers, json=data) as response:
                    if response.status == 200:
                        account_info = await response.json()
                        log_info(
                            f"アカウント情報を取得しました: @{account_info.get('username', 'unknown')}"
                        )
                        return account_info
                    else:
                        log_error(
                            f"アカウント情報の取得に失敗しました ({retry + 1}/{MAX_RETRIES}): ステータス {response.status}"
                        )
                        if retry == MAX_RETRIES - 1:
                            return None
        except Exception as e:
            log_error(
                f"アカウント情報の取得エラー ({retry + 1}/{MAX_RETRIES}): {type(e).__name__}: {e}"
            )
            if retry == MAX_RETRIES - 1:
                return None

        # 次回のリトライまで待機
        await asyncio.sleep(RETRY_DELAY * (retry + 1))

    return None


async def process_note(note, stats):
    """ノートを処理してリアクションを追加する"""
    # リプライやリノートの処理
    if note.get("replyId") or note.get("renoteId"):
        if not REACT_TO_REPLIES:
            log_info(f"除外: リプライまたはリノート (ID: {note.get('id', 'unknown')})")
            stats["skipped_notes"] += 1
            return False
        # リプライ/リノートにリアクションする設定の場合は処理継続

    # 許可する公開範囲を設定
    allowed_visibilities = ["public", "home"]
    if REACT_TO_FOLLOWERS:
        allowed_visibilities.append("followers")

    # フィルタリング条件:
    # 1. visibilityが許可されたリスト内
    # 2. Bot自身のアカウントのノートは除外
    # 3. 空ノートは除外
    if (
        note.get("visibility") in allowed_visibilities
        and note.get("user", {}).get("id") != BOT_USER_ID
        and note.get("text")
    ):
        username = note.get("user", {}).get("username", "unknown")
        note_text = note.get("text", "")

        # リアクション確率に基づいてスキップするかどうか判断
        if random.random() > REACTION_PROBABILITY:
            log_info(f"確率によりスキップ: @{username} のノート")
            stats["skipped_notes"] += 1
            return False

        try:
            # リアクションを生成
            reaction = await generate_reaction_with_custom_emojis(note_text)

            # リアクションを付与
            success = await add_reaction(note.get("id"), reaction)

            if success:
                # ログ出力
                log_reaction(username, note_text, reaction)
                stats["reactions_sent"] += 1

                # 連続リクエスト防止のためのスリープ
                await asyncio.sleep(1)
                return True
            else:
                stats["errors"] += 1
                return False
        except Exception as e:
            log_error(f"リアクション処理エラー: {type(e).__name__}: {e}")
            stats["errors"] += 1
            return False

    return False


async def display_stats(stats):
    """統計情報を表示する"""
    current_time = time.time()
    if current_time - stats["last_stats_time"] > stats["stats_interval"]:
        elapsed_hours = (current_time - stats["start_time"]) / 3600
        log_info(
            f"統計情報 ({elapsed_hours:.1f}時間): 処理済み {stats['processed_notes']}件, "
            f"リアクション {stats['reactions_sent']}件, スキップ {stats['skipped_notes']}件, "
            f"エラー {stats['errors']}件"
        )
        stats["last_stats_time"] = current_time


async def connect_websocket(reconnect_delay=WS_RECONNECT_DELAY_INITIAL):
    """WebSocketに接続して監視を開始する"""
    try:
        async with websockets.connect(
            MISSKEY_WS_URL, user_agent_header=WS_USER_AGENT
        ) as ws:
            log_ws(f"WebSocketに接続しました (User-Agent: {WS_USER_AGENT})")
            log_ws("ホームタイムラインをサブスクライブします...")

            # ホームタイムラインをサブスクライブする
            subscribe_message = {
                "type": "connect",
                "body": {"channel": "homeTimeline", "id": "home"},
            }

            await ws.send(json.dumps(subscribe_message))
            log_ws("ホームタイムラインをサブスクライブしました")

            # 統計情報
            stats = {
                "processed_notes": 0,
                "reactions_sent": 0,
                "skipped_notes": 0,
                "errors": 0,
                "start_time": time.time(),
                "last_stats_time": time.time(),
                "stats_interval": 3600,  # 1時間ごとに統計表示
            }

            # ハートビートの時間管理
            last_heartbeat = time.time()
            heartbeat_interval = 30  # 30秒ごとにハートビート送信

            while True:
                # WebSocketの非同期読み取りとタイムアウト確認を組み合わせる
                try:
                    message = await asyncio.wait_for(
                        ws.recv(), timeout=heartbeat_interval
                    )
                    data = json.loads(message)

                    if data["type"] == "channel" and data["body"]["type"] == "note":
                        note = data["body"]["body"]
                        stats["processed_notes"] += 1

                        await process_note(note, stats)

                        await display_stats(stats)

                except asyncio.TimeoutError:
                    # タイムアウトしたらハートビート送信
                    current_time = time.time()
                    if current_time - last_heartbeat >= heartbeat_interval:
                        log_ws("ハートビート送信...")
                        await ws.send(json.dumps({"type": "ping"}))
                        last_heartbeat = current_time
                    continue

        return True

    except websockets.exceptions.ConnectionClosed as e:
        log_error(f"WebSocket接続が閉じられました: {type(e).__name__}: {e}")
        return False

    except Exception as e:
        log_error(f"WebSocket接続エラー: {type(e).__name__}: {e}")
        return False


async def main():
    """WebSocketに接続し、ホームタイムラインを監視"""
    # アカウント情報を取得して表示
    account_info = await get_account_info()
    if account_info:
        global BOT_USER_ID
        BOT_USER_ID = account_info.get("id")
        log_info(f"Bot ID: {BOT_USER_ID}")
    else:
        log_error("アカウント情報の取得に失敗しました。終了します。")
        return

    log_info("WebSocketに接続しています...")

    print(f"\n{Colors.HEADER}{'=' * 80}{Colors.ENDC}")
    print(
        f"{Colors.HEADER}{Colors.BOLD} Misskey リアクションボット 稼働中 {Colors.ENDC}"
    )
    print(f"{Colors.HEADER}{'=' * 80}{Colors.ENDC}\n")

    # 再接続用の変数
    reconnect_delay = WS_RECONNECT_DELAY_INITIAL

    while True:
        # WebSocketに接続
        success = await connect_websocket()

        if not success:
            log_info(f"{reconnect_delay}秒後に再接続を試みます...")
            await asyncio.sleep(reconnect_delay)

            # 指数バックオフで再接続間隔を延長（最大値まで）
            reconnect_delay = min(
                reconnect_delay * WS_RECONNECT_FACTOR, WS_RECONNECT_DELAY_MAX
            )
        else:
            # 正常終了した場合は再接続間隔をリセット
            reconnect_delay = WS_RECONNECT_DELAY_INITIAL


if __name__ == "__main__":
    asyncio.run(main())
