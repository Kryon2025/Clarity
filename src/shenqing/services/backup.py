"""用户数据备份 / 恢复（v0.14）。

- create_backup(dest_path)：把设置/空间/统计/应用时长/AI/睡眠/黑名单/应用清单/插件数据打包为 zip，
  zip 内附 manifest.json（app/version/createdAt/files）；
- restore_backup(zip_path)：校验 manifest → 先做 pre-import 兜底备份 → 只解压白名单文件/目录，
  防 zip 路径穿越；非法 zip / 非本应用备份返回失败原因。
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import zipfile
from datetime import datetime
from pathlib import Path, PurePosixPath

from ..consts import APP_VERSION
from ..paths import app_data_dir

logger = logging.getLogger("shenqing.backup")

MANIFEST_NAME = "manifest.json"
APP_MARK = "ShenQing"
BACKUP_DIR_NAME = "backups"
PLUGIN_DATA_DIR = "plugin_data"

#: (源相对路径, zip 内路径)
BACKUP_FILES: tuple[tuple[str, str], ...] = (
    ("settings.json", "settings.json"),
    ("spaces.json", "spaces.json"),
    ("stats.json", "stats.json"),
    ("app_usage.json", "app_usage.json"),
    ("app_usage_overrides.json", "app_usage_overrides.json"),
    ("ai_chats.json", "ai_chats.json"),
    ("ai_usage.json", "ai_usage.json"),
    ("settings/sleep.json", "sleep.json"),
    ("blocklist.json", "blocklist.json"),
    ("apps.json", "apps.json"),
)

#: zip 内路径 → 恢复时写入的相对路径（默认同名）
ARCHIVE_TARGETS: dict[str, str] = {
    archive: source for source, archive in BACKUP_FILES
}

#: 兼容旧备份里直接存 settings/sleep.json 的情况
ARCHIVE_TARGETS["settings/sleep.json"] = "settings/sleep.json"


def backup_dir() -> Path:
    return app_data_dir() / BACKUP_DIR_NAME


def default_backup_name(now: datetime | None = None) -> str:
    return f"深清备份-{(now or datetime.now()):%Y%m%d-%H%M}.zip"


def create_backup(dest_path: str | Path) -> tuple[bool, str]:
    """把用户数据打包成 zip；成功返回 (True, 路径)，失败 (False, 原因)。"""
    root = app_data_dir()
    dest = Path(dest_path)
    if dest.exists() and dest.is_dir():
        return False, "目标是目录，请选择文件"
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        temp = dest.with_name(dest.name + ".part")
        files: list[str] = []
        with zipfile.ZipFile(temp, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for source_rel, archive_name in BACKUP_FILES:
                source = root / source_rel
                if not source.is_file():
                    continue
                archive.write(source, archive_name)
                files.append(archive_name)
            plugin_root = root / PLUGIN_DATA_DIR
            if plugin_root.is_dir():
                for item in sorted(plugin_root.rglob("*")):
                    if not item.is_file():
                        continue
                    archive_name = f"{PLUGIN_DATA_DIR}/" + item.relative_to(plugin_root).as_posix()
                    archive.write(item, archive_name)
                    files.append(archive_name)
            manifest = {
                "app": APP_MARK,
                "version": APP_VERSION,
                "createdAt": datetime.now().isoformat(timespec="seconds"),
                "files": files,
            }
            archive.writestr(
                MANIFEST_NAME,
                json.dumps(manifest, ensure_ascii=False, indent=2),
            )
        os.replace(temp, dest)
        logger.info("备份完成：%s（%s 个文件）", dest, len(files))
        return True, str(dest)
    except (OSError, zipfile.BadZipFile, ValueError) as exc:
        logger.warning("创建备份失败：%s", exc)
        try:
            temp.unlink()  # type: ignore[possibly-undefined]
        except (OSError, UnboundLocalError, NameError):
            pass
        return False, f"创建备份失败：{exc}"


def _safe_archive_name(name: str) -> bool:
    text = str(name or "").replace("\\", "/")
    if not text or text.startswith("/") or text.startswith("~"):
        return False
    if re.match(r"^[A-Za-z]:", text):
        return False
    parts = PurePosixPath(text).parts
    return ".." not in parts and "." not in parts


def _read_manifest(archive: zipfile.ZipFile) -> tuple[dict | None, str]:
    try:
        raw = archive.read(MANIFEST_NAME)
        data = json.loads(raw.decode("utf-8", errors="replace"))
    except KeyError:
        return None, "备份缺少 manifest.json，不是深清备份"
    except (OSError, json.JSONDecodeError, ValueError, UnicodeDecodeError) as exc:
        return None, f"manifest.json 损坏：{exc}"
    if not isinstance(data, dict):
        return None, "manifest.json 格式不正确"
    if str(data.get("app") or "") != APP_MARK:
        return None, "不是深清备份（app 标识不匹配）"
    if not str(data.get("version") or "").strip():
        return None, "备份缺少版本信息"
    return data, ""


def restore_backup(zip_path: str | Path) -> tuple[bool, str]:
    """从 zip 恢复用户数据；成功返回 (True, "")，失败 (False, 原因)。"""
    path = Path(zip_path)
    if not path.is_file():
        return False, "备份文件不存在"
    if not zipfile.is_zipfile(path):
        return False, "不是有效的 zip 备份文件"
    try:
        with zipfile.ZipFile(path) as archive:
            manifest, error = _read_manifest(archive)
            if manifest is None:
                return False, error
            names = [name for name in archive.namelist() if not name.endswith("/")]
            unsafe = [name for name in names if name != MANIFEST_NAME and not _safe_archive_name(name)]
            if unsafe:
                logger.warning("拒绝导入：备份包含非法路径 %s", unsafe[0])
                return False, f"备份包含非法路径，已拒绝导入：{unsafe[0]}"
            targets: list[tuple[str, str]] = []
            for name in names:
                if name == MANIFEST_NAME:
                    continue
                if name in ARCHIVE_TARGETS:
                    targets.append((name, ARCHIVE_TARGETS[name]))
                elif name.startswith(f"{PLUGIN_DATA_DIR}/"):
                    targets.append((name, name))
            if not targets:
                return False, "备份里没有可恢复的数据文件"
            # 先做导入前兜底备份
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            pre_path = backup_dir() / f"pre-import-{stamp}.zip"
            ok, message = create_backup(pre_path)
            if not ok:
                return False, f"创建导入前备份失败：{message}"
            root = app_data_dir().resolve()
            for archive_name, target_rel in targets:
                target = (root / target_rel).resolve()
                if not str(target).startswith(str(root)):
                    return False, f"拒绝写入越界路径：{target_rel}"
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(archive_name) as source, target.open("wb") as handle:
                    shutil.copyfileobj(source, handle)
            logger.info("备份恢复完成：%s", path)
            return True, ""
    except (OSError, zipfile.BadZipFile, ValueError, RuntimeError) as exc:
        logger.warning("恢复备份失败：%s", exc)
        return False, f"恢复备份失败：{exc}"
