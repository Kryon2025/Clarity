"""Windows SMTC（System Media Transport Controls）媒体信息服务。

后台线程跑 asyncio 轮询当前媒体会话（标题/艺术家/播放状态/进度/专辑封面），
通过 Qt 信号把数据交给主线程；提供播放/暂停、上一首、下一首控制。
封面（thumbnail）按曲目写入临时目录缓存，读取失败一律静默降级为 ""。
不依赖第三方包以外的 GUI，WinRT 不可用时整体降级为 available=False。
"""

from __future__ import annotations

import asyncio
import hashlib
import tempfile
import threading
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Signal

#: 封面缓存目录（系统临时目录下按曲目 sha1 命名，v0.22 起给灵动岛提供专辑封面）
ART_CACHE_DIR: Path = Path(tempfile.gettempdir()) / "shenqing-media-art"
#: 缓存目录最多保留的封面文件数（按 mtime 清理最旧的）
ART_CACHE_KEEP = 40
#: 单张封面最大字节数，超过视为异常数据
_MAX_ART_BYTES = 8 * 1024 * 1024
#: 同一曲目读不到封面时最多重试的轮询次数（避免每秒都去碰 WinRT）
_ART_RETRIES = 3

#: 常见播放器 AUMID/进程名 -> 友好名
_APP_NAMES: dict[str, str] = {
    "spotify": "Spotify",
    "cloudmusic": "网易云音乐",
    "netease": "网易云音乐",
    "qqmusic": "QQ 音乐",
    "kugou": "酷狗音乐",
    "kuwo": "酷我音乐",
    "bilibili": "哔哩哔哩",
    "potplayer": "PotPlayer",
    "vlc": "VLC",
    "music.ui": "Groove 音乐",
    "zunemusic": "Groove 音乐",
    "foobar": "foobar2000",
    "chrome": "Chrome",
    "msedge": "Edge",
    "firefox": "Firefox",
}


def _friendly_app(app_id: str) -> str:
    lowered = (app_id or "").lower()
    for key, name in _APP_NAMES.items():
        if key in lowered:
            return name
    if "!" in app_id:
        tail = app_id.split("!")[0].split(".")[-1]
        return tail.capitalize() or "媒体"
    return app_id or "媒体"


# ---------- 封面缓存（纯逻辑，不依赖 winrt，方便单测） ----------
def art_cache_path(title: str, artist: str, album: str, extension: str = "png") -> Path:
    """同一首曲目永远得到同一个缓存路径；不同曲目互不相同。"""
    key = f"{title or ''}|{artist or ''}|{album or ''}".encode("utf-8", "replace")
    digest = hashlib.sha1(key).hexdigest()[:16]
    ext = (extension or "png").strip().lstrip(".").lower() or "png"
    return ART_CACHE_DIR / f"{digest}.{ext}"


def detect_image_ext(data: bytes) -> str:
    """按文件头识别图片格式，返回 png/jpg/bmp/webp；识别不了返回 ""。"""
    if not isinstance(data, (bytes, bytearray, memoryview)):
        return ""
    try:
        raw = bytes(data)
    except Exception:  # noqa: BLE001
        return ""
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if raw.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if raw.startswith(b"BM"):
        return "bmp"
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "webp"
    return ""


def prune_art_cache(directory: Path, keep: int = ART_CACHE_KEEP) -> int:
    """只保留 directory 里最新的 keep 个文件（按 mtime），返回删除数量。"""
    try:
        directory = Path(directory)
        if not directory.is_dir():
            return 0
        files = [item for item in directory.iterdir() if item.is_file()]
    except OSError:
        return 0
    limit = max(0, int(keep))
    if len(files) <= limit:
        return 0

    def _mtime(item: Path) -> float:
        try:
            return item.stat().st_mtime
        except OSError:
            return 0.0

    files.sort(key=lambda item: (_mtime(item), item.name), reverse=True)
    removed = 0
    for stale in files[limit:]:
        try:
            stale.unlink()
            removed += 1
        except OSError:
            pass
    return removed


def save_art_bytes(data: Any, title: str, artist: str, album: str) -> str:
    """校验图片字节并落盘到缓存目录，返回绝对路径；非图片/写失败返回 ""。"""
    ext = detect_image_ext(data)
    if not ext:
        return ""
    try:
        payload = bytes(data)
        target = art_cache_path(title, artist, album, ext)
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            # 同曲目重复轮询：内容没变就只刷新 mtime，避免每秒重写文件
            if target.is_file() and target.read_bytes() == payload:
                target.touch()
                prune_art_cache(target.parent, ART_CACHE_KEEP)
                return str(target)
        except OSError:
            pass
        temp = target.with_name(f"{target.name}.tmp")
        temp.write_bytes(payload)
        temp.replace(target)
        prune_art_cache(target.parent, ART_CACHE_KEEP)
        return str(target)
    except OSError:
        return ""


def _reader_bytes(reader: Any, count: int) -> bytes:
    """从 DataReader 里取出 count 字节；pywinrt 版本不同，取法多路兜底。"""
    try:
        from winrt.system import Array, UInt8

        buffer = Array(UInt8, count)
        reader.read_bytes(buffer)
        data = bytes(memoryview(buffer))
        if data:
            return data
    except Exception:  # noqa: BLE001 - 旧版本 / 接口差异
        pass
    try:
        ibuffer = reader.read_buffer(count)
    except Exception:  # noqa: BLE001
        return b""
    for cast in (lambda buf: bytes(memoryview(buf)), bytes):
        try:
            data = cast(ibuffer)
        except Exception:  # noqa: BLE001
            continue
        if data:
            return data
    return b""


class MediaSmtcService(QObject):
    """轮询 SMTC 会话；数据以 dict 形式发 changed 信号。"""

    changed = Signal(dict)

    def __init__(self, parent: QObject | None = None, interval: float = 1.0) -> None:
        super().__init__(parent)
        self._interval = max(0.4, interval)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._available = False
        self._last: dict[str, Any] = {}
        self._lock = threading.Lock()
        # 封面缓存：("标题|艺术家|专辑", 路径, 已失败次数)，避免每秒重复读 WinRT 缩略图
        self._art_state: tuple[str, str, int] = ("", "", 0)

    # ---------- 生命周期 ----------
    @property
    def available(self) -> bool:
        return self._available

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        try:  # 预热导入，让 available 尽早反映真实情况
            from winrt.windows.media.control import (  # noqa: F401
                GlobalSystemMediaTransportControlsSessionManager,
            )

            self._available = True
        except Exception:  # noqa: BLE001 - 没装 WinRT 就降级
            self._available = False
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="shenqing-smtc", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        loop = self._loop
        if loop is not None and loop.is_running():
            try:
                loop.call_soon_threadsafe(loop.stop)
            except RuntimeError:
                pass

    # ---------- 后台线程 ----------
    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._poll())
        except Exception:  # noqa: BLE001
            pass
        finally:
            try:
                loop.close()
            except Exception:  # noqa: BLE001
                pass
            self._loop = None

    async def _poll(self) -> None:
        from winrt.windows.media.control import (
            GlobalSystemMediaTransportControlsSessionManager as Manager,
        )

        last_emit = 0.0
        try:
            manager = await Manager.request_async()
        except Exception:  # noqa: BLE001
            self._available = False
            return

        while not self._stop.is_set():
            try:
                payload = await self._read(manager)
            except Exception:  # noqa: BLE001
                payload = self._empty()
            # 只在有变化或每 2 秒兜底刷新时发信号，避免刷爆 UI
            if payload != self._last:
                self._last = payload
                try:
                    self.changed.emit(payload)
                except RuntimeError:
                    return
            await asyncio.sleep(self._interval)

    async def _read(self, manager: Any) -> dict[str, Any]:
        session = manager.get_current_session()
        if session is None:
            return self._empty()
        props = await session.try_get_media_properties_async()
        info = session.get_playback_info()
        timeline = session.get_timeline_properties()
        playing = False
        if info is not None:
            try:
                from winrt.windows.media.control import (
                    GlobalSystemMediaTransportControlsSessionPlaybackStatus as Status,
                )

                playing = info.playback_status == Status.PLAYING
            except Exception:  # noqa: BLE001
                playing = False
        position = 0.0
        duration = 0.0
        if timeline is not None:
            try:
                position = float(timeline.position.total_seconds())
                duration = float(timeline.end_time.total_seconds())
            except Exception:  # noqa: BLE001
                position = duration = 0.0
        title = getattr(props, "title", "") or ""
        artist = getattr(props, "artist", "") or ""
        album = getattr(props, "album_title", "") or ""
        app_id = session.source_app_user_model_id or ""
        if not title:
            return self._empty()
        art = await self._art_for(props, title, artist, album)
        return {
            "has": True,
            "title": title,
            "artist": artist,
            "album": album,
            "art": art,
            "app": _friendly_app(app_id),
            "appId": app_id,
            "playing": playing,
            "position": round(position, 1),
            "duration": round(duration, 1),
        }

    @staticmethod
    def _empty() -> dict[str, Any]:
        return {
            "has": False,
            "title": "",
            "artist": "",
            "album": "",
            "art": "",
            "app": "",
            "appId": "",
            "playing": False,
            "position": 0.0,
            "duration": 0.0,
        }

    # ---------- 专辑封面 ----------
    async def _art_for(self, props: Any, title: str, artist: str, album: str) -> str:
        """当前曲目的封面路径：同曲目复用缓存，连续读不到就放弃（不拖慢轮询）。"""
        key = f"{title}|{artist}|{album}"
        cached_key, cached_path, tries = self._art_state
        if cached_key == key:
            if cached_path and Path(cached_path).is_file():
                return cached_path
            if not cached_path and tries >= _ART_RETRIES:
                return ""
        art = await self._read_art(props, title, artist, album)
        self._art_state = (key, art, tries + 1 if cached_key == key else 1)
        return art

    async def _read_art(self, props: Any, title: str, artist: str, album: str) -> str:
        """读 SMTC 缩略图并落盘缓存；任何异常都静默返回 ""，绝不中断轮询。"""
        try:
            thumbnail = getattr(props, "thumbnail", None)
            if thumbnail is None:
                return ""
            data = await self._read_thumbnail_bytes(thumbnail)
            if not data:
                return ""
            return save_art_bytes(data, title, artist, album)
        except Exception:  # noqa: BLE001 - 封面失败不能影响媒体轮询
            return ""

    @staticmethod
    async def _read_thumbnail_bytes(thumbnail: Any) -> bytes:
        """IRandomAccessStreamReference -> bytes；拿不到就返回 b""。"""
        try:
            from winrt.windows.storage.streams import DataReader
        except Exception:  # noqa: BLE001 - 没装 WinRT / 版本不匹配
            return b""
        try:
            stream = await thumbnail.open_read_async()
        except Exception:  # noqa: BLE001 - 无权限 / 会话已关闭
            return b""
        if stream is None:
            return b""
        try:
            size = int(stream.size or 0)
        except Exception:  # noqa: BLE001
            return b""
        if size <= 0 or size > _MAX_ART_BYTES:
            return b""
        try:
            reader = DataReader(stream)
            loaded = int(await reader.load_async(size) or 0)
        except Exception:  # noqa: BLE001
            return b""
        if loaded <= 0:
            return b""
        return _reader_bytes(reader, loaded)

    # ---------- 控制 ----------
    def _run_coroutine(self, factory) -> None:  # noqa: ANN001
        loop = self._loop
        if loop is None or not loop.is_running():
            return
        try:
            asyncio.run_coroutine_threadsafe(factory(), loop)
        except Exception:  # noqa: BLE001
            pass

    def toggle(self) -> None:
        self._run_coroutine(self._toggle)

    def next(self) -> None:
        self._run_coroutine(self._next)

    def previous(self) -> None:
        self._run_coroutine(self._previous)

    async def _toggle(self) -> None:
        from winrt.windows.media.control import (
            GlobalSystemMediaTransportControlsSessionManager as Manager,
        )

        manager = await Manager.request_async()
        session = manager.get_current_session()
        if session is not None:
            await session.try_toggle_play_pause_async()

    async def _next(self) -> None:
        from winrt.windows.media.control import (
            GlobalSystemMediaTransportControlsSessionManager as Manager,
        )

        manager = await Manager.request_async()
        session = manager.get_current_session()
        if session is not None:
            await session.try_skip_next_async()

    async def _previous(self) -> None:
        from winrt.windows.media.control import (
            GlobalSystemMediaTransportControlsSessionManager as Manager,
        )

        manager = await Manager.request_async()
        session = manager.get_current_session()
        if session is not None:
            await session.try_skip_previous_async()
