#!/usr/bin/env python3
import json
import asyncio
import aiohttp
import os
from dotenv import load_dotenv

# 環境変数のロード
load_dotenv("config/.env")

# Misskey API設定
MISSKEY_HTTP_HOST = os.getenv("MISSKEY_HTTP_HOST")
MISSKEY_TOKEN = os.getenv("MISSKEY_TOKEN")
API_PROTOCOL = (
    "https"
    if os.getenv("API_SECURE", "true").lower() in ["true", "1", "yes"]
    else "http"
)
MISSKEY_API_URL = f"{API_PROTOCOL}://{MISSKEY_HTTP_HOST}/api"

# Gemini API設定
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# 感情や用途ごとの分類カテゴリ
EMOTION_CATEGORIES = {
    "happy": ["happy", "smile", "laugh", "joy", "grin", "yay", "喜"],
    "sad": ["sad", "cry", "tear", "泣", "悲しい", "しょんぼり"],
    "love": ["love", "heart", "愛", "好き", "ハート", "daisuki"],
    "angry": ["angry", "rage", "mad", "怒", "プンプン", "むかつく"],
    "surprised": ["surprised", "shock", "wow", "omg", "驚", "えっ", "ビックリ"],
    "thinking": ["think", "hmm", "ponder", "考え", "悩む", "うーん"],
    "fun": ["lol", "lmao", "rofl", "草", "www", "笑", "ワロタ"],
    "food": ["food", "eat", "yum", "delicious", "飯", "食べ物", "美味しい"],
    "agreement": ["agree", "yes", "ok", "good", "nice", "はい", "いいね"],
    "disagreement": ["disagree", "no", "bad", "nope", "いや", "だめ"],
    "celebration": ["congrats", "party", "celebrate", "おめでとう", "祝"],
    "greeting": ["hello", "hi", "hey", "welcome", "こんにちは", "よろしく"],
    "sleep": ["sleep", "tired", "疲れ", "眠い", "寝る"],
    "animal": ["cat", "dog", "bird", "animal", "猫", "犬", "動物"],
    "cute": ["cute", "kawaii", "かわいい", "可愛い", "カワイイ"],
    "cool": ["cool", "awesome", "great", "かっこいい", "すごい", "イケてる"],
    "music": ["music", "song", "dance", "音楽", "歌", "ダンス"],
    "work": ["work", "job", "busy", "仕事", "忙しい", "頑張る"],
    "weather": ["rain", "sun", "snow", "hot", "cold", "雨", "晴れ", "雪"],
    "tech": ["pc", "computer", "tech", "code", "パソコン", "技術"],
    "gaming": ["game", "play", "ゲーム", "プレイ", "gaming"],
    "sports": ["sports", "exercise", "スポーツ", "運動", "exercise"],
    "nature": ["nature", "plant", "flower", "tree", "自然", "植物", "花"],
}


async def fetch_custom_emojis():
    """Misskeyサーバーからカスタム絵文字を取得"""
    url = f"{MISSKEY_API_URL}/emojis"
    headers = {"Content-Type": "application/json"}
    data = {"i": MISSKEY_TOKEN}  # トークンを環境変数から取得

    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=headers, json=data) as response:
            if response.status == 200:
                result = await response.json()
                return result.get("emojis", [])
            else:
                print(f"絵文字の取得に失敗しました: {response.status}")
                return []


async def categorize_emojis_with_gemini(emojis):
    import google.generativeai as genai
    import json

    # Gemini APIの設定
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel("gemini-2.0-flash-lite")

    # Process emojis in chunks of 50
    chunk_size = 50
    all_categories = {}

    for i in range(0, len(emojis), chunk_size):
        chunk = emojis[i : i + chunk_size]
        emoji_list_text = ""
        for emoji in chunk:
            name = emoji.get("name", "")
            orig_cat = emoji.get("category", "")
            emoji_list_text += f"名前: {name}, 元のカテゴリ: {orig_cat}\n"

        allowed_categories = list(EMOTION_CATEGORIES.keys())
        allowed_categories_str = ", ".join([f'"{cat}"' for cat in allowed_categories])
        system_prompt = f"""Misskeyのカスタム絵文字再分類タスク:
- 各絵文字には元のカテゴリが設定されていますが、これらを以下の「許可されたカテゴリ」のいずれかに再分類してください。
- 【重要】絶対に許可されたカテゴリのみを使用し、新しいカテゴリは作成しないでください。
- 絵文字は必ず以下のカテゴリのいずれかに分類してください。該当するカテゴリがない場合は「other」に分類してください。

許可されたカテゴリ一覧:
{allowed_categories_str}

以下は各カテゴリに関連するキーワードです:
{json.dumps(EMOTION_CATEGORIES, ensure_ascii=False, indent=2)}

結果は必ず以下のJSON形式で返してください（使用するカテゴリキーは上記の許可されたカテゴリのみ）:
  {{"categories": {{"happy": ["emoji_name1", "emoji_name2"], "sad": ["emoji_name3"], ...}}}}
"""
        user_prompt = f"絵文字一覧:\n{emoji_list_text}"
        prompt = system_prompt + "\n" + user_prompt

        result = await model.generate_content_async(prompt)
        response_text = result.text.strip()
        if not response_text:
            raise Exception(
                f"Gemini categorization failed: API returned an empty response for chunk starting at index {i}"
            )
        try:
            # Remove markdown code block syntax if present
            import re

            json_match = re.search(r"```json\n(.*?)```", response_text, re.DOTALL)
            if json_match:
                response_text = json_match.group(1).strip()

            # Fix trailing commas in JSON which are valid in JavaScript but not in JSON
            response_text = re.sub(r",\s*([}\]])", r"\1", response_text)
            response_json = json.loads(response_text)
        except Exception as e:
            raise Exception(
                f"Gemini chunk categorization failed: {e}, response_text: {response_text}"
            )

        # Merge the categories from this chunk into all_categories
        chunk_categories = response_json.get("categories", {})
        for cat, emoji_names in chunk_categories.items():
            if cat in all_categories:
                all_categories[cat].extend(emoji_names)
            else:
                all_categories[cat] = emoji_names

    # After processing all chunks, filter the categories to only allowed ones
    allowed = set(EMOTION_CATEGORIES.keys())
    if "other" not in allowed:
        allowed.add("other")
    filtered_categories = {key: [] for key in allowed}
    for cat, emoji_names in all_categories.items():
        if cat in allowed:
            filtered_categories[cat].extend(emoji_names)
        else:
            filtered_categories["other"].extend(emoji_names)
    return {"categories": filtered_categories}


def categorize_emoji(emoji, raw_categories):
    """絵文字を用途/感情カテゴリーに分類"""
    name = emoji["name"].lower()
    category = emoji.get("category", "").lower()

    # カテゴリーを追跡するリスト
    assigned_categories = []

    # 名前とカテゴリーを組み合わせたテキスト（検索用）
    search_text = f"{name} {category}"

    # 各感情カテゴリでキーワードマッチング
    for emotion, keywords in EMOTION_CATEGORIES.items():
        for keyword in keywords:
            if keyword.lower() in search_text:
                assigned_categories.append(emotion)
                break

    # 元のカテゴリも保持
    if category:
        # 元のカテゴリを「raw_」プレフィックスで追加
        raw_category = f"raw_{category}"
        if raw_category not in raw_categories:
            raw_categories.append(raw_category)
        assigned_categories.append(raw_category)

    # カテゴリが一つも割り当てられなかった場合は「other」に分類
    if not assigned_categories:
        assigned_categories.append("other")

    return assigned_categories


async def process_and_save_emojis():
    """絵文字を取得・処理・保存する"""
    print("カスタム絵文字を取得しています...")
    all_emojis = await fetch_custom_emojis()

    if not all_emojis:
        print("絵文字を取得できませんでした。")
        return

    print(f"{len(all_emojis)}個のカスタム絵文字を取得しました。")

    # 元のemojis.jsonも保存
    with open("data/emojis_raw.json", "w", encoding="utf-8") as f:
        json.dump({"emojis": all_emojis}, f, ensure_ascii=False, indent=2)

    print("元の絵文字データをdata/emojis_raw.jsonに保存しました。")

    # カテゴリ別に整理（Geminiによる新しいカテゴリ分けを試行）
    try:
        gemini_result = await categorize_emojis_with_gemini(all_emojis)
        gemini_categories = gemini_result.get("categories", {})
        categorized_emojis = {}
        for category, emoji_names in gemini_categories.items():
            categorized_emojis[category] = [
                emoji for emoji in all_emojis if emoji.get("name") in emoji_names
            ]
        print("Geminiによる絵文字の新しいカテゴリ分けに成功しました。")
    except Exception as e:
        print(f"Geminiによるカテゴリ分けに失敗しました: {e}")
        print("従来の手法でカテゴリ分けを行います。")
        categorized_emojis = {cat: [] for cat in EMOTION_CATEGORIES.keys()}
        categorized_emojis["other"] = []  # その他カテゴリも追加
        for emoji in all_emojis:
            emoji_categories = categorize_emoji(emoji, [])
            emoji_with_categories = emoji.copy()
            emoji_with_categories["emotion_categories"] = emoji_categories
            for cat in emoji_categories:
                if cat in categorized_emojis:
                    categorized_emojis[cat].append(emoji_with_categories)
                else:
                    categorized_emojis.setdefault(cat, []).append(emoji_with_categories)

    # 処理結果の統計
    stats = {cat: len(emojis) for cat, emojis in categorized_emojis.items()}

    # 結果を保存
    result = {
        "stats": stats,
        "categories": list(categorized_emojis.keys()),
        "emotion_categories": list(EMOTION_CATEGORIES.keys()),
        "categorized_emojis": categorized_emojis,
    }

    with open("data/emojis_processed.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print("処理済み絵文字データをdata/emojis_processed.jsonに保存しました。")
    print("カテゴリ別統計:")
    for cat, count in sorted(stats.items(), key=lambda x: x[1], reverse=True):
        if count > 0:
            print(f"  {cat}: {count}個")


if __name__ == "__main__":
    asyncio.run(process_and_save_emojis())
