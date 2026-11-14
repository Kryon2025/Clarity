"""用 AI 批量翻译 .ts 条目（GitHub Actions 或本地）。

用法：
    DEEPSEEK_API_KEY=sk-xxx python scripts/i18n_bot.py fr_FR ja_JP
    python scripts/i18n_bot.py --force fr_FR ja_JP        # 重译「当前译文仍与英文占位相同」的条目
    python scripts/i18n_bot.py --limit 20 fr_FR          # 只翻译前 20 条（调试）

- 有 DEEPSEEK_API_KEY：走 DeepSeek（OpenAI 兼容）接口；
- 没有 Key：自动回退到免费直连 https://text.pollinations.ai/openai（openai-fast），无需配置；
- 只处理未完成 / 空 / 英文占位 的条目，保留占位符 %1 %2 与换行；
- 翻译完写回 .ts（标记 finished），再由 i18n.py compile 生成 .qm。
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

LOCALES = Path("src/shenqing/locales")
API_KEY = os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("TRANSLATE_API_KEY", "")
if API_KEY:
    API_BASE = os.environ.get("TRANSLATE_API_BASE", "https://api.deepseek.com/v1")
    MODEL = os.environ.get("TRANSLATE_MODEL", "deepseek-chat")
else:
    API_BASE = os.environ.get("TRANSLATE_API_BASE", "https://text.pollinations.ai/openai")
    MODEL = os.environ.get("TRANSLATE_MODEL", "openai-fast")
BATCH = int(os.environ.get("TRANSLATE_BATCH", "18"))

LANG_NAMES = {"fr_FR": "French", "ja_JP": "Japanese", "en_US": "English"}


def call_llm(messages: list[dict]) -> str:
    payload = json.dumps(
        {"model": MODEL, "messages": messages, "temperature": 0.2}, ensure_ascii=False
    ).encode("utf-8")
    headers = {"Content-Type": "application/json", "User-Agent": "ShenQing-i18n-bot"}
    if API_KEY:
        headers["Authorization"] = "Bearer " + API_KEY
    request = urllib.request.Request(
        API_BASE + "/chat/completions", data=payload, headers=headers, method="POST"
    )
    with urllib.request.urlopen(request, timeout=180) as response:  # noqa: S310
        data = json.loads(response.read().decode("utf-8"))
    return str(data["choices"][0]["message"]["content"])


def _strip_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[4:] if text.startswith("json") else text
    return text.strip()


def translate_batch(sources: list[str], target_language: str) -> list[str]:
    joined = json.dumps(sources, ensure_ascii=False)
    prompt = (
        "You are a professional software localizer. Translate the following Chinese UI strings "
        "into " + target_language + ". Keep placeholders like %1 %2 and \\n newlines exactly "
        "as-is. Return ONLY a JSON array of strings in the same order, no commentary."
        "\n\n" + joined
    )
    last_error = ""
    for attempt in range(3):
        try:
            result = json.loads(_strip_fence(call_llm([{"role": "user", "content": prompt}])))
            if isinstance(result, list) and len(result) == len(sources):
                return [str(item) for item in result]
            last_error = "unexpected result shape"
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)
        time.sleep(3 + attempt * 3)
    raise RuntimeError(last_error or "translation failed")


def _load_english() -> dict[str, str]:
    path = LOCALES / "en_US.ts"
    mapping: dict[str, str] = {}
    if not path.exists():
        return mapping
    tree = ET.parse(path)
    for ctx in tree.getroot().iter("context"):
        for message in ctx.iter("message"):
            source = message.findtext("source") or ""
            tr = message.find("translation")
            if tr is not None and (tr.text or "").strip():
                mapping[source] = (tr.text or "").strip()
    return mapping


def main(argv: list[str]) -> int:
    force = "--force" in argv
    limit = None
    args = [item for item in argv if not item.startswith("--")]
    for index, item in enumerate(argv):
        if item == "--limit" and index + 1 < len(argv):
            try:
                limit = int(argv[index + 1])
            except ValueError:
                pass
    codes = [code for code in args if code in LANG_NAMES] or ["fr_FR", "ja_JP"]
    english = _load_english() if force else {}
    print("api:", API_BASE, "| model:", MODEL, "| key:", bool(API_KEY), "| force:", force)
    for code in codes:
        if code == "en_US":
            continue
        path = LOCALES / (code + ".ts")
        if not path.exists():
            print("missing", path)
            continue
        tree = ET.parse(path)
        targets: list[tuple[ET.Element, str]] = []
        for ctx in tree.getroot().iter("context"):
            for message in ctx.iter("message"):
                source = message.findtext("source") or ""
                if not source.strip():
                    continue
                tr = message.find("translation")
                if tr is None:
                    tr = ET.SubElement(message, "translation")
                text = (tr.text or "").strip()
                unfinished = tr.get("type") == "unfinished" or not text
                placeholder = force and english.get(source, "") == text
                if unfinished or placeholder:
                    targets.append((tr, source))
        if limit:
            targets = targets[:limit]
        print(code + ":", len(targets), "strings to translate")
        done = 0
        for index in range(0, len(targets), BATCH):
            chunk = targets[index:index + BATCH]
            sources = [item[1] for item in chunk]
            try:
                translated = translate_batch(sources, LANG_NAMES[code])
            except Exception as exc:  # noqa: BLE001
                print("  batch", index // BATCH + 1, "failed:", exc)
                continue
            for (tr, _source), text in zip(chunk, translated):
                tr.attrib.pop("type", None)
                tr.text = text
                done += 1
            print("  batch", index // BATCH + 1, "ok", done, "/", len(targets), flush=True)
            time.sleep(2)
        tree.write(path, encoding="utf-8", xml_declaration=True)
        print(code, "finished:", done)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
