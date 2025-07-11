"""Constants for Misskey Reaction Bot."""

from typing import Dict, List

# Emotion categories for emoji classification
EMOTION_CATEGORIES: Dict[str, List[str]] = {
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

# Default emoji fallback
DEFAULT_EMOJI = "👍"

# File paths
EMOJI_DATA_PATH = "data/emojis_processed.json"
RAW_EMOJI_DATA_PATH = "data/emojis_raw.json"

# WebSocket channel IDs
HOME_TIMELINE_CHANNEL = "homeTimeline"
HOME_TIMELINE_ID = "home"

# WebSocket heartbeat interval (seconds)
HEARTBEAT_INTERVAL = 30

# Visibility levels
PUBLIC_VISIBILITY = "public"
HOME_VISIBILITY = "home"
FOLLOWERS_VISIBILITY = "followers"

# Note processing delay (seconds)
NOTE_PROCESSING_DELAY = 1.0
