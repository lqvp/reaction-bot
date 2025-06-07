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
from src.preprocess_emojis import EMOTION_CATEGORIES
import logging
from collections import defaultdict
from pydantic import BaseModel, Field

# 環境変数のロード
load_dotenv("config/.env")


class Config:
    def __init__(self):
        # Misskey API設定
        self.MISSKEY_HTTP_HOST = os.getenv("MISSKEY_HTTP_HOST")
        self.MISSKEY_WS_HOST = os.getenv("MISSKEY_WS_HOST")
        self.MISSKEY_TOKEN = os.getenv("MISSKEY_TOKEN")

        # API設定
        self.API_SECURE = os.getenv("API_SECURE", "true").lower() in [
            "true",
            "1",
            "yes",
        ]
        self.API_PROTOCOL = "https" if self.API_SECURE else "http"
        self.MISSKEY_API_URL = f"{self.API_PROTOCOL}://{self.MISSKEY_HTTP_HOST}/api"

        # WebSocket設定
        self.WS_SECURE = os.getenv("WS_SECURE", "true").lower() in ["true", "1", "yes"]
        self.WS_PROTOCOL = "wss" if self.WS_SECURE else "ws"
        self.MISSKEY_WS_URL = f"{self.WS_PROTOCOL}://{self.MISSKEY_WS_HOST}/streaming?i={self.MISSKEY_TOKEN}"

        # ロギング設定
        self.LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
        self.MAX_NOTE_TEXT_LENGTH = int(os.getenv("MAX_NOTE_TEXT_LENGTH", "50"))

        # リアクション設定
        self.REACTION_PROBABILITY = float(os.getenv("REACTION_PROBABILITY", "1.0"))
        self.REACT_TO_REPLIES = os.getenv("REACT_TO_REPLIES", "false").lower() in [
            "true",
            "1",
            "yes",
        ]
        self.REACT_TO_FOLLOWERS = os.getenv("REACT_TO_FOLLOWERS", "false").lower() in [
            "true",
            "1",
            "yes",
        ]

        # Gemini API設定
        self.GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
        self.GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash-lite")

        # 再試行設定
        self.MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))
        self.RETRY_DELAY = int(os.getenv("RETRY_DELAY", "2"))

        # WebSocket再接続設定
        self.WS_RECONNECT_DELAY_INITIAL = int(
            os.getenv("WS_RECONNECT_DELAY_INITIAL", "5")
        )
        self.WS_RECONNECT_DELAY_MAX = int(os.getenv("WS_RECONNECT_DELAY_MAX", "60"))
        self.WS_RECONNECT_FACTOR = float(os.getenv("WS_RECONNECT_FACTOR", "1.5"))

        # WebSocketのUser-Agent設定
        self.WS_USER_AGENT = os.getenv("WS_USER_AGENT", "MisskeyReactionBot/1.0")
        self.STATS_INTERVAL = int(
            os.getenv("STATS_INTERVAL", "3600")
        )  # 統計表示間隔（秒）


config = Config()


async def periodic_stats_logger(stats, interval_seconds):
    """一定間隔で統計情報をログに出力する"""
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            current_time_monotonic = time.monotonic()
            elapsed_seconds = current_time_monotonic - stats["start_time_monotonic"]

            # 総稼働時間を HH:MM:SS 形式に変換
            hours, remainder = divmod(elapsed_seconds, 3600)
            minutes, seconds = divmod(remainder, 60)
            uptime_str = f"{int(hours):02}:{int(minutes):02}:{int(seconds):02}"

            log_message = f"\n--- 統計情報 (稼働時間: {uptime_str}) ---"
            log_message += f"\n  処理ノート数: {stats['processed_notes']}"
            log_message += f"\n  リアクション送信数: {stats['reactions_sent']}"
            log_message += f"\n  スキップノート数: {stats['skipped_notes']}"
            log_message += f"\n  エラー発生数: {stats['errors']}"
            log_message += f"\n  WebSocket切断回数: {stats['ws_disconnect_count']}"

            log_message += "\n  リアクション絵文字別カウント:"
            if stats["reaction_counts"]:
                # sortedでキーの順序を固定し、表示の揺らぎを防ぐ
                for emoji, count in sorted(stats["reaction_counts"].items()):
                    log_message += f"\n    - {emoji}: {count}"
            else:
                log_message += "\n    - (まだリアクションはありません)"

            log_message += "\n  リアクション生成ソース:"
            log_message += f"\n    - Gemini API成功: {stats['gemini_success_count']}"
            log_message += f"\n    - ランダム絵文字フォールバック: {stats['random_fallback_count']}"
            log_message += f"\n    - Unicode絵文字フォールバック: {stats['unicode_fallback_count']}"

            if elapsed_seconds > 0:
                notes_per_hour = (stats["processed_notes"] / elapsed_seconds) * 3600
                reactions_per_hour = (stats["reactions_sent"] / elapsed_seconds) * 3600
                errors_per_hour = (stats["errors"] / elapsed_seconds) * 3600
                log_message += "\n  平均値 (1時間あたり):"
                log_message += f"\n    - 平均処理ノート数: {notes_per_hour:.2f}"
                log_message += f"\n    - 平均リアクション数: {reactions_per_hour:.2f}"
                log_message += f"\n    - 平均エラー数: {errors_per_hour:.2f}"

            log_message += "\n-----------------------------------"
            logging.info(log_message)

        except Exception as e:
            logging.error(
                f"統計情報のロギング中にエラーが発生しました: {e}", exc_info=True
            )


# Logging Configuration
numeric_level = getattr(logging, config.LOG_LEVEL.upper(), None)
if not isinstance(numeric_level, int):
    numeric_level = logging.INFO  # default to INFO if LOG_LEVEL is invalid
logging.basicConfig(
    level=numeric_level,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


def log_reaction(username, note_text, reaction):
    # テキストを短く切り詰める
    short_text = (
        note_text[: config.MAX_NOTE_TEXT_LENGTH] + "..."
        if len(note_text) > config.MAX_NOTE_TEXT_LENGTH
        else note_text
    )
    short_text = short_text.replace("\n", " ")  # Remove newlines for cleaner log
    logging.info(f"REACTION: @{username}: {short_text} -> {reaction}")


# WebSocketイベントのログ専用関数
def log_ws(message):
    """WebSocketイベントのログ専用関数"""
    logging.debug(f"WS: {message}")


# Gemini APIの設定
genai.configure(api_key=config.GEMINI_API_KEY)
model = genai.GenerativeModel(config.GEMINI_MODEL)

BOT_USER_ID = None
# 有効な絵文字名のセット（高速検索用）
VALID_EMOJI_NAMES = set()


# カスタム絵文字データのロード
def load_emoji_data():
    """前処理済みの絵文字データをロードする"""
    global VALID_EMOJI_NAMES

    for retry in range(config.MAX_RETRIES):
        try:
            with open("data/emojis_processed.json", "r", encoding="utf-8") as f:
                emoji_data = json.load(f)

            # 有効な絵文字名のセットを作成
            VALID_EMOJI_NAMES.clear()
            for category in emoji_data["categorized_emojis"]:
                for emoji in emoji_data["categorized_emojis"][category]:
                    VALID_EMOJI_NAMES.add(emoji["name"])

            logging.info(
                f"カスタム絵文字データをロードしました: {len(emoji_data['categories'])}カテゴリ, {len(VALID_EMOJI_NAMES)}個の絵文字"
            )
            return emoji_data
        except (FileNotFoundError, json.JSONDecodeError) as e:
            logging.error(
                f"カスタム絵文字データの読み込みに失敗しました ({retry + 1}/{config.MAX_RETRIES}): {type(e).__name__}: {e}"
            )
            if retry < config.MAX_RETRIES - 1:
                wait_time = config.RETRY_DELAY * (retry + 1)
                logging.warning(f"{wait_time}秒後に再試行します...")
                time.sleep(wait_time)
            else:
                logging.warning(
                    "src/preprocess_emojis.pyを実行して、絵文字データを生成してください。"
                )
                return None


# 絵文字データをロード
EMOJI_DATA = load_emoji_data()


class ReactionResponse(BaseModel):
    reactions: str = Field(
        description="提案されたMisskeyカスタム絵文字 (例: :blobcat_uwu:)"
    )
    # :name: 形式で、name部分は英数字、アンダースコア、ハイフンのみを許可


def create_prompt_for_reaction(note_text, emoji_examples):
    """リアクション生成用のプロンプトを作成する"""
    return f"""
    以下のノートに対して、文脈に最も適したMisskeyカスタム絵文字を1つ提案してください。

    ルール:
    1. ノートの感情、トーン、内容に合わせて最適なカスタム絵文字を選ぶこと
    2. 単調にならないよう、多様な絵文字を使用すること
    3. 返答は必ず `:emoji_name:` 形式のカスタム絵文字のリストとすること
    4. 通常の Unicode 絵文字 (例: 😊 👍) は使わないでください
    5. カスタム絵文字の名前は、後述する「利用可能なカスタム絵文字のカテゴリーと例」に示されている形式および名前の範囲から選んでください。これらの例にない名前や、形式の異なる名前は使用しないでください。
    6. カスタム絵文字は必ず一個だけ返してください

    利用可能なカスタム絵文字のカテゴリーと例:
    {chr(10).join(emoji_examples)}

    出力は以下のJSON形式で返してください：
    {{"reactions": ":emoji_name:"}}

    ノート: "{note_text}"
    """


async def generate_reaction_with_custom_emojis(note_text, stats):
    """Gemini APIを使ってカスタム絵文字のリアクションを生成（非同期・Structured Output使用）"""
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
    for retry in range(config.MAX_RETRIES):
        try:
            # structured output用の設定
            generation_config = genai.types.GenerationConfig(
                response_mime_type="application/json",
                response_schema=ReactionResponse,
            )
            # 安全性設定 (必要に応じて調整)
            safety_settings = [
                {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
                {
                    "category": "HARM_CATEGORY_SEXUALLY_EXPLICIT",
                    "threshold": "BLOCK_NONE",
                },
                {
                    "category": "HARM_CATEGORY_DANGEROUS_CONTENT",
                    "threshold": "BLOCK_NONE",
                },
            ]

            response = await model.generate_content_async(
                contents=prompt,
                generation_config=generation_config,
                safety_settings=safety_settings,
            )

            reaction = None  # 初期化
            if response.text:
                try:
                    # Pydanticモデルでパース・検証
                    parsed_data = ReactionResponse.model_validate_json(response.text)
                    reaction = parsed_data.reactions
                    if not is_valid_custom_emoji(reaction):
                        logging.warning(
                            f"Structured Outputで得られた絵文字が無効: {reaction}, Response: {response.text}"
                        )
                        reaction = None  # 無効ならNoneに戻す
                except (
                    Exception
                ) as parse_error:  # PydanticのValidationErrorやjson.JSONDecodeError
                    logging.warning(
                        f"Structured Outputのパース/検証エラー: {parse_error}, Response: {response.text}"
                    )
                    reaction = None  # パース失敗時もNone
            else:
                logging.warning(f"Geminiからのレスポンスが空です。Response: {response}")
                reaction = None  # 空レスポンス時もNone

            if reaction:
                logging.info(f"リアクションを抽出: {reaction}")
                stats["gemini_success_count"] += 1
                return reaction
            else:
                logging.warning(f"抽出失敗、再試行 ({retry + 1}/{config.MAX_RETRIES})")
                if retry == config.MAX_RETRIES - 1:
                    # 最大リトライ回数に達したらランダムな絵文字を返す
                    final_random_reaction = get_random_emoji()
                    if final_random_reaction:  # Noneでないことを確認
                        stats["random_fallback_count"] += 1
                    else:  # もしget_random_emojiがNoneを返すようなことがあれば、エラーとして記録
                        logging.error(
                            "generate_reaction_with_custom_emojis: 最終フォールバックでget_random_emojiがNoneを返しました"
                        )
                        stats["errors"] += 1
                    return final_random_reaction
        except Exception as e:
            logging.error(
                f"リアクション生成エラー ({retry + 1}/{config.MAX_RETRIES}): {type(e).__name__}: {e}",
                exc_info=True,
            )
            stats["errors"] += 1
            if retry == config.MAX_RETRIES - 1:
                # 最大リトライ回数に達したらランダムな絵文字を返す
                final_random_reaction = get_random_emoji()
                if final_random_reaction:  # Noneでないことを確認
                    stats["random_fallback_count"] += 1
                else:  # もしget_random_emojiがNoneを返すようなことがあれば、エラーとして記録
                    logging.error(
                        "generate_reaction_with_custom_emojis: 最終フォールバックでget_random_emojiがNoneを返しました"
                    )
                    stats["errors"] += 1
                return final_random_reaction
            await asyncio.sleep(config.RETRY_DELAY * (retry + 1))


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


async def generate_reaction_fallback(note_text, stats):
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

    for retry in range(config.MAX_RETRIES):
        try:
            result = await model.generate_content_async(prompt)
            response_text = result.text.strip()
            logging.info(f"フォールバックリアクション生成: {response_text}")

            try:
                response_json = json.loads(response_text)
                reaction = response_json.get("reaction")
                if reaction:
                    stats["unicode_fallback_count"] += 1
                    return reaction
                # JSON形式だがreactionキーがない場合、またはJSONパース失敗に備える
                logging.warning(
                    f"フォールバック: JSONからreactionキーが見つからないか、パース失敗。レスポンス全体から絵文字を試みます: {response_text}"
                )
            except (json.JSONDecodeError, KeyError) as e:
                logging.warning(
                    f"JSONデコードエラー ({retry + 1}/{config.MAX_RETRIES}): {type(e).__name__}: {e}"
                )
                # 単純な絵文字の抽出を試みる
                emoji_match = re.search(
                    r'["\']([\p{Emoji}]+)["\']', response_text, re.UNICODE
                )
                if emoji_match:
                    stats["unicode_fallback_count"] += 1
                    return emoji_match.group(1)

                if retry == config.MAX_RETRIES - 1:
                    stats["unicode_fallback_count"] += 1  # 最終フォールバックもカウント
                    return "👍"  # 最終的なフォールバック
        except Exception as e:
            stats["errors"] += 1
            logging.error(
                f"フォールバックリアクション生成エラー ({retry + 1}/{config.MAX_RETRIES}): {type(e).__name__}: {e}",
                exc_info=True,
            )
            # Geminiからのレスポンスが期待通りでない場合、リトライ
            logging.warning(
                f"フォールバック: 期待した形式のレスポンスが得られませんでした。再試行 ({retry + 1}/{config.MAX_RETRIES})"
            )
            if retry == config.MAX_RETRIES - 1:
                logging.info(
                    "フォールバック: 最大リトライ回数に達したため、デフォルトの絵文字を返します。"
                )
                stats["unicode_fallback_count"] += 1
                return "👍"
            await asyncio.sleep(config.RETRY_DELAY * (retry + 1))


async def add_reaction(note_id, reaction, stats):
    """ノートにリアクションを付与する"""
    url = f"{config.MISSKEY_API_URL}/notes/reactions/create"
    headers = {"Content-Type": "application/json"}
    data = {"i": config.MISSKEY_TOKEN, "noteId": note_id, "reaction": reaction}

    for retry in range(config.MAX_RETRIES):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers, json=data) as response:
                    result = await response.text()
                    if response.status == 200 or response.status == 204:
                        logging.info(
                            f"ノート {note_id} にリアクション {reaction} を付与しました"
                        )
                        return True
                    else:
                        logging.error(
                            f"リアクション付与エラー ({retry + 1}/{config.MAX_RETRIES}): ステータス {response.status}, レスポンス: {result}"
                        )
                        stats["errors"] += 1
                        if retry == config.MAX_RETRIES - 1:
                            return False
        except Exception as e:
            logging.error(
                f"リアクションAPI接続エラー ({retry + 1}/{config.MAX_RETRIES}): {type(e).__name__}: {e}",
                exc_info=True,
            )
            stats["errors"] += 1
            if retry == config.MAX_RETRIES - 1:
                return False

        # 次回のリトライまで待機
        await asyncio.sleep(config.RETRY_DELAY * (retry + 1))

    return False


async def get_account_info(stats):
    """Misskey APIを使ってアカウント情報を取得（/api/i エンドポイント）"""
    url = f"{config.MISSKEY_API_URL}/i"
    headers = {"Content-Type": "application/json"}
    data = {"i": config.MISSKEY_TOKEN}

    for retry in range(config.MAX_RETRIES):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers, json=data) as response:
                    if response.status == 200:
                        account_info = await response.json()
                        logging.info(
                            f"アカウント情報を取得しました: @{account_info.get('username', 'unknown')}"
                        )
                        return account_info
                    else:
                        error_message = await response.text()
                        logging.error(
                            f"アカウント情報取得APIエラー ({retry + 1}/{config.MAX_RETRIES}): ステータス {response.status} - {error_message}"
                        )
                        stats["errors"] += 1
                        if retry == config.MAX_RETRIES - 1:
                            return None
        except Exception as e:
            logging.error(
                f"アカウント情報取得中の接続エラー ({retry + 1}/{config.MAX_RETRIES}): {type(e).__name__}: {e}"
            )
            stats["errors"] += 1
            if retry == config.MAX_RETRIES - 1:
                return None

        # 次回のリトライまで待機
        await asyncio.sleep(config.RETRY_DELAY * (retry + 1))

    return None


async def process_note(note, stats):
    """ノートを処理してリアクションを追加する"""
    # リプライやリノートの処理
    if note.get("replyId") or note.get("renoteId"):
        if not config.REACT_TO_REPLIES:
            logging.info(
                f"除外: リプライまたはリノート (ID: {note.get('id', 'unknown')})"
            )
            stats["skipped_notes"] += 1
            return False
        # リプライ/リノートにリアクションする設定の場合は処理継続

    # 許可する公開範囲を設定
    allowed_visibilities = ["public", "home"]
    if config.REACT_TO_FOLLOWERS:
        allowed_visibilities.append("followers")

    # フィルタリング条件:
    # 1. visibilityが許可されたリスト内
    # 2. Bot自身のアカウントのノートは除外
    # 3. 空ノートは除外
    user_id = note.get("user", {}).get("id")
    note_text_content = note.get("text")
    note_id = note.get("id", "unknown")  # for logging

    if user_id == BOT_USER_ID:
        logging.info(f"除外: 自分自身のノート (ID: {note_id})")
        stats["skipped_notes"] += 1
        return False

    if not note_text_content:
        logging.info(f"除外: 空のノート (ID: {note_id})")
        stats["skipped_notes"] += 1
        return False

    if note.get("visibility") not in allowed_visibilities:
        logging.info(
            f"除外: 許可されていない公開範囲 '{note.get('visibility')}' (ID: {note_id})"
        )
        stats["skipped_notes"] += 1
        return False

    # 上記チェックをすべて通過した場合に処理を続行
    if True:
        username = note.get("user", {}).get("username", "unknown")
        note_text = note.get("text", "")

        # リアクション確率に基づいてスキップするかどうか判断
        if random.random() > config.REACTION_PROBABILITY:
            logging.info(f"確率によりスキップ: @{username} のノート")
            stats["skipped_notes"] += 1
            return False

        try:
            reaction = await generate_reaction_with_custom_emojis(note_text, stats)
            if not reaction:
                reaction = await generate_reaction_fallback(note_text, stats)

            if reaction:
                if await add_reaction(note.get("id"), reaction, stats):
                    stats["reactions_sent"] += 1
                    stats["reaction_counts"][reaction] += 1
                    log_reaction(username, note_text, reaction)
                    await asyncio.sleep(1)  # 連続リクエスト防止
                    return True
                else:
                    # add_reaction内でエラーカウントされるのでここでは何もしない
                    return False
            else:
                logging.warning(
                    f"最終的にリアクションを生成できませんでした: @{username} のノート"
                )
                stats["skipped_notes"] += 1
                return False
        except Exception as e:
            logging.error(
                f"リアクション処理エラー: {type(e).__name__}: {e}", exc_info=True
            )
            stats["errors"] += 1  # ここで一般的なエラーをカウント
            stats["errors"] += 1
            return False

    return False


async def connect_websocket(stats, reconnect_delay=None):
    """WebSocketに接続して監視を開始する"""
    if reconnect_delay is None:
        reconnect_delay = config.WS_RECONNECT_DELAY_INITIAL
    try:
        async with websockets.connect(
            config.MISSKEY_WS_URL, user_agent_header=config.WS_USER_AGENT
        ) as ws:
            log_ws(f"WebSocketに接続しました (User-Agent: {config.WS_USER_AGENT})")
            log_ws("ホームタイムラインをサブスクライブします...")

            # ホームタイムラインをサブスクライブする
            subscribe_message = {
                "type": "connect",
                "body": {"channel": "homeTimeline", "id": "home"},
            }

            await ws.send(json.dumps(subscribe_message))
            log_ws("ホームタイムラインをサブスクライブしました")

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
        logging.error(f"WebSocket接続が閉じられました: {type(e).__name__}: {e}")
        stats["ws_disconnect_count"] += 1
        stats["errors"] += 1
        return False

    except Exception as e:
        logging.error(f"WebSocket接続エラー: {type(e).__name__}: {e}")
        stats["errors"] += 1
        return False


async def main():
    """WebSocketに接続し、ホームタイムラインを監視"""

    # 統計情報辞書の初期化
    stats = {
        "processed_notes": 0,
        "reactions_sent": 0,
        "skipped_notes": 0,
        "errors": 0,
        "ws_disconnect_count": 0,
        "gemini_success_count": 0,
        "random_fallback_count": 0,
        "unicode_fallback_count": 0,
        "reaction_counts": defaultdict(int),
        "start_time_monotonic": time.monotonic(),  # 稼働時間計測用
    }

    # 統計ロガータスクを開始
    asyncio.create_task(periodic_stats_logger(stats, config.STATS_INTERVAL))

    # アカウント情報を取得して表示
    account_info = await get_account_info(stats)
    if account_info:
        global BOT_USER_ID
        BOT_USER_ID = account_info.get("id")
        logging.info(f"Bot ID: {BOT_USER_ID}")
    else:
        logging.error("アカウント情報の取得に失敗しました。終了します。")
        stats["errors"] += 1  # アカウント情報取得失敗もエラーとしてカウント
        return

    logging.info("WebSocketに接続しています...")

    logging.info(
        "\n================================================================================"
    )
    logging.info(" Misskey リアクションボット 稼働中 ")
    logging.info(
        "================================================================================\n"
    )

    # 再接続用の変数
    reconnect_delay = config.WS_RECONNECT_DELAY_INITIAL

    while True:
        # WebSocketに接続
        success = await connect_websocket(stats, reconnect_delay)

        if not success:
            logging.info(f"{reconnect_delay}秒後に再接続を試みます...")
            await asyncio.sleep(reconnect_delay)

            # 指数バックオフで再接続間隔を延長（最大値まで）
            reconnect_delay = min(
                reconnect_delay * config.WS_RECONNECT_FACTOR,
                config.WS_RECONNECT_DELAY_MAX,
            )
        else:
            # 正常終了した場合は再接続間隔をリセット
            reconnect_delay = config.WS_RECONNECT_DELAY_INITIAL


if __name__ == "__main__":
    asyncio.run(main())
