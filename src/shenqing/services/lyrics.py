"""歌词：从网易云公开接口取当前歌曲的 LRC 并解析成时间轴。

只用于专注遮罩上的灵动岛显示当前一句歌词；接口失败时静默返回空（不弹错、不影响播放控制）。
"""
from __future__ import annotations

import json
import threading
import urllib.parse
import urllib.request

SEARCH_URL = "https://music.163.com/api/search/get"
LYRIC_URL = "https://music.163.com/api/song/lyric"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://music.163.com/",
}
TIMEOUT = 6
_CACHE: dict[str, list[dict]] = {}
_CACHE_LOCK = threading.Lock()
_CACHE_LIMIT = 64


def _cache_key(title: str, artist: str) -> str:
    return (str(title or "").strip() + "|" + str(artist or "").strip()).lower()


def _cache_get(key: str) -> list[dict] | None:
    with _CACHE_LOCK:
        lines = _CACHE.get(key)
        return list(lines) if lines is not None else None


def _cache_put(key: str, lines: list[dict]) -> None:
    with _CACHE_LOCK:
        if len(_CACHE) >= _CACHE_LIMIT:
            _CACHE.pop(next(iter(_CACHE)), None)
        _CACHE[key] = list(lines)


def parse_lrc(text: str) -> list[dict]:
    """把 LRC 解析成 [{'t': 秒, 'text': 歌词}]，按时间升序；忽略空行/纯标注。"""
    lines: list[dict] = []
    if not text:
        return lines
    for raw in str(text).splitlines():
        line = raw.strip()
        if not line:
            continue
        # [mm:ss.xx][mm:ss.xxx] 歌词（可能一行多个时间戳）
        stamps: list[float] = []
        rest = line
        while rest.startswith("["):
            end = rest.find("]")
            if end <= 0:
                break
            tag = rest[1:end]
            rest = rest[end + 1:]
            if ":" in tag:
                mm, _, ss = tag.partition(":")
                try:
                    stamps.append(int(mm) * 60 + float(ss))
                except ValueError:
                    continue
        if not stamps:
            continue
        content = rest.strip()
        if not content:
            continue
        # 过滤制作人员信息行（纯标注太多会盖住歌词）
        if content.startswith(("作词", "作曲", "编曲", "制作人", "混音", "母带", "监制", "录音")):
            continue
        for seconds in stamps:
            lines.append({"t": round(seconds, 2), "text": content})
    lines.sort(key=lambda item: item["t"])
    return lines


def pick_line(lines: list[dict], position: float) -> tuple[str, str]:
    """返回 (当前歌词, 下一句)；时间未到第一句时返回空。"""
    if not lines:
        return "", ""
    pos = max(0.0, float(position or 0))
    current = ""
    following = ""
    # 前奏还没到第一句时，提前把第一句当作「下一句」
    try:
        if pos + 0.15 < float(lines[0].get("t", 0)):
            return "", str(lines[0].get("text", ""))
    except (TypeError, ValueError):
        pass
    for index, line in enumerate(lines):
        try:
            start = float(line.get("t", 0))
        except (TypeError, ValueError):
            continue
        if start <= pos + 0.15:
            current = str(line.get("text", ""))
            following = str(lines[index + 1].get("text", "")) if index + 1 < len(lines) else ""
        else:
            break
    return current, following


def _post_json(url: str, params: dict) -> dict:
    data = urllib.parse.urlencode(params).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=HEADERS, method="POST")
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        payload = response.read().decode("utf-8", "replace")
    try:
        return json.loads(payload)
    except ValueError:
        return {}


def fetch_lyrics(title: str, artist: str) -> dict:
    """查歌词；返回 {'lines': [...], 'error': ''}。网络失败时 error 非空、lines 为空。"""
    name = str(title or "").strip()
    if not name:
        return {"lines": [], "error": "没有歌名"}
    key = _cache_key(name, artist)
    cached = _cache_get(key)
    if cached is not None:
        return {"lines": cached, "error": ""}
    try:
        query = (name + " " + str(artist or "")).strip()
        found = _post_json(SEARCH_URL, {"s": query, "type": 1, "limit": 1})
        songs = ((found.get("result") or {}).get("songs") or [])
        if not songs:
            found = _post_json(SEARCH_URL, {"s": name, "type": 1, "limit": 1})
            songs = ((found.get("result") or {}).get("songs") or [])
        if not songs:
            return {"lines": [], "error": "没有搜索到这首歌"}
        song_id = int(songs[0].get("id") or 0)
        if song_id <= 0:
            return {"lines": [], "error": "歌曲 id 无效"}
        lyric = _post_json(LYRIC_URL, {"id": song_id, "lv": 1, "kv": 0, "tv": -1})
        text = str((lyric.get("lrc") or {}).get("lyric") or "")
        lines = parse_lrc(text)
        if not lines:
            return {"lines": [], "error": "这首歌没有歌词"}
        _cache_put(key, lines)
        return {"lines": lines, "error": ""}
    except Exception as exc:  # noqa: BLE001 - 歌词失败不能影响播放
        return {"lines": [], "error": str(exc)}
