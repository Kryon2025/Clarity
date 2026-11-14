"""GitHub 发布源同步（GitHub Releases -> 商店版本/下载地址）。

开发者提交条目时必须填写 GitHub 仓库 / 发布页地址，商店后台据此自动同步版本：

- 地址解析：只接受 http(s)://github.com/<owner>/<repo> 与其 /releases 页面；
- 取数：GitHub API repos/{owner}/{repo}/releases/latest，6 秒超时（可配置）；
  配置 GITHUB_TOKEN 可把匿名 60 次/小时的限额提高（CI 发布场景够用）；
- 版本：release 的 tag_name（自动去掉 v 前缀，例如 v1.2.3 -> 1.2.3）；
- 下载地址：优先资产名含 Setup / Portable 的（桌面端安装包），否则取第一个
  资产，再退化成 release 页面地址；
- 本模块只做「网络 + 解析」，不碰数据库：DB 读写由 main.py 负责，测试可以
  直接把 fetch_latest_release 换成假实现，不必联网。
"""

from __future__ import annotations

import json
import re
import socket
import urllib.error
import urllib.parse
import urllib.request

__all__ = [
    "DEFAULT_TIMEOUT",
    "GITHUB_API_ROOT",
    "GitHubSyncError",
    "fetch_latest_release",
    "is_github_url",
    "latest_release_api_url",
    "normalize_github_url",
    "parse_github_repo",
    "parse_release",
    "pick_download_url",
    "release_version",
    "sync_item",
]

#: GitHub REST API 根地址（测试里可用假 fetcher 绕过）
GITHUB_API_ROOT = "https://api.github.com"
#: 单次请求超时（秒）：GitHub 偶发慢响应，6 秒内没结果就当失败，不拖住同步
DEFAULT_TIMEOUT = 6.0
#: 桌面端安装包资产名关键字（按优先级排列）
ASSET_HINTS = ("setup", "portable")
#: User-Agent（GitHub API 强制要求）
USER_AGENT = "ShenQingStore/1.0 (+https://github.com/Kryon2025/Clarity)"
#: GitHub 用户/组织名规则（简化版，够拦住明显垃圾输入）
OWNER_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")
#: 仓库名规则（允许点、下划线、短横线）
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")
#: 接受的主机名
GITHUB_HOSTS = ("github.com", "www.github.com")


class GitHubSyncError(RuntimeError):
    """同步失败（网络 / 限额 / 仓库不存在 / 内容无法解析）；上层转成 last_sync_error。"""


def _split_github_url(url: str) -> tuple[str, str, bool] | None:
    """拆出 (owner, repo, 是否发布页)；不是合法 GitHub 仓库地址时返回 None。"""
    text = str(url or "").strip()
    if not text:
        return None
    if "://" not in text:
        text = "https://" + text
    try:
        parsed = urllib.parse.urlsplit(text)
    except ValueError:
        return None
    if parsed.scheme not in ("http", "https"):
        return None
    if (parsed.hostname or "").lower() not in GITHUB_HOSTS:
        return None
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2:
        return None
    owner, repo = parts[0], parts[1]
    if repo.lower().endswith(".git"):
        repo = repo[:-4]
    is_releases = False
    if len(parts) > 2:
        # 只允许 /releases、/releases/tag/<tag>、/releases/latest
        if parts[2] != "releases":
            return None
        is_releases = True
    if not OWNER_RE.fullmatch(owner) or not REPO_RE.fullmatch(repo):
        return None
    return owner, repo, is_releases


def parse_github_repo(url: str) -> tuple[str, str] | None:
    """GitHub 仓库 / 发布页地址 -> (owner, repo)；不合法返回 None。"""
    parts = _split_github_url(url)
    if parts is None:
        return None
    return parts[0], parts[1]


def is_github_url(url: str) -> bool:
    """是否是合法的 GitHub 仓库或发布页地址（提交时必填字段的校验依据）。"""
    return parse_github_repo(url) is not None


def normalize_github_url(url: str) -> str:
    """归一化后入库：https://github.com/<owner>/<repo>[/releases]；不合法返回空串。"""
    parts = _split_github_url(url)
    if parts is None:
        return ""
    owner, repo, is_releases = parts
    base = "https://github.com/" + owner + "/" + repo
    return base + "/releases" if is_releases else base


def latest_release_api_url(owner: str, repo: str) -> str:
    """最新发布的 API 地址（owner/repo 已由 parse_github_repo 校验）。"""
    return GITHUB_API_ROOT + "/repos/" + owner + "/" + repo + "/releases/latest"


def fetch_latest_release(
    owner: str,
    repo: str,
    *,
    token: str = "",
    timeout: float = DEFAULT_TIMEOUT,
) -> dict:
    """请求 GitHub releases/latest，返回解析后的 JSON 对象。

    失败抛 GitHubSyncError（文案直接写进 items.last_sync_error，给开发者看）。
    """
    url = latest_release_api_url(owner, repo)
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": USER_AGENT,
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = "Bearer " + str(token)
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=max(1.0, float(timeout))) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise GitHubSyncError("该仓库还没有发布 Release（或仓库不存在）") from None
        if exc.code in (403, 429):
            raise GitHubSyncError(
                "GitHub API 调用次数超限，请稍后重试或配置 GITHUB_TOKEN"
            ) from None
        raise GitHubSyncError("GitHub 返回错误：HTTP " + str(exc.code)) from None
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        if isinstance(reason, (TimeoutError, socket.timeout)):
            raise GitHubSyncError(
                "连接 GitHub 超时（" + str(int(timeout)) + " 秒）"
            ) from None
        raise GitHubSyncError("无法连接 GitHub：" + str(reason)) from None
    except (TimeoutError, socket.timeout):
        raise GitHubSyncError("连接 GitHub 超时（" + str(int(timeout)) + " 秒）") from None
    except OSError as exc:
        raise GitHubSyncError("无法连接 GitHub：" + str(exc)) from None
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise GitHubSyncError("GitHub 返回内容不是合法 JSON") from None
    if not isinstance(payload, dict):
        raise GitHubSyncError("GitHub 返回内容格式不正确")
    return payload


def release_version(payload: dict) -> str:
    """release -> 版本号：tag_name 去 v 前缀（v1.2.3 -> 1.2.3），最多 32 字符。

    与 items.version 的长度限制一致；tag 为空时退回 release 名称。
    """
    tag = str(payload.get("tag_name") or "").strip()
    if not tag:
        tag = str(payload.get("name") or "").strip()
    if tag[:1] in ("v", "V") and tag[1:2].isdigit():
        tag = tag[1:]
    return tag[:32]


def _asset_links(payload: dict) -> list[tuple[str, str]]:
    """(资产名小写, 下载地址) 列表；坏数据跳过。"""
    assets = payload.get("assets")
    links: list[tuple[str, str]] = []
    if not isinstance(assets, list):
        return links
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        link = str(asset.get("browser_download_url") or "").strip()
        name = str(asset.get("name") or "").strip().lower()
        if link:
            links.append((name, link))
    return links


def pick_download_url(payload: dict) -> str:
    """下载地址：资产名匹配 Setup / Portable 优先，否则第一个资产，再退发布页。"""
    links = _asset_links(payload)
    for hint in ASSET_HINTS:
        for name, link in links:
            if hint in name:
                return link
    if links:
        return links[0][1]
    return str(payload.get("html_url") or "").strip()


def parse_release(payload: dict) -> dict:
    """release JSON -> {version, download_url, tag_name, published_at, html_url}。"""
    return {
        "version": release_version(payload),
        "download_url": pick_download_url(payload),
        "tag_name": str(payload.get("tag_name") or "").strip(),
        "published_at": str(payload.get("published_at") or "").strip(),
        "html_url": str(payload.get("html_url") or "").strip(),
    }


def sync_item(
    item: dict,
    *,
    token: str = "",
    timeout: float = DEFAULT_TIMEOUT,
) -> dict:
    """同步单个条目：返回 {ok, version, download_url, error}（不抛异常）。

    网络/解析失败都折算成 error 文案，由调用方写进 items.last_sync_error；
    条目其它字段一律不改动。
    """
    payload = item or {}
    url = str(payload.get("github_url") or "").strip()
    repo = parse_github_repo(url)
    if repo is None:
        return {
            "ok": False,
            "version": "",
            "download_url": "",
            "error": "GitHub 地址无效，请填写仓库或发布页地址",
        }
    try:
        release = fetch_latest_release(repo[0], repo[1], token=token, timeout=timeout)
    except GitHubSyncError as exc:
        return {"ok": False, "version": "", "download_url": "", "error": str(exc)}
    info = parse_release(release)
    if not info["version"] and not info["download_url"]:
        return {
            "ok": False,
            "version": "",
            "download_url": "",
            "error": "GitHub 最新发布里没有可用的版本号或下载地址",
        }
    return {
        "ok": True,
        "version": info["version"],
        "download_url": info["download_url"],
        "error": "",
    }
