"""生成镜像仓库用的 update.json 清单（发布流程 / 本地发布时调用）。

用法：
    python scripts/make_update_manifest.py 0.20.0 > packaging/update.json

说明：资产地址默认指向 GitHub Release（镜像仓库无需再传安装包）；
可用 --base-url 覆盖为镜像/对象存储地址。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

GITHUB_REPO = "Kryon2025/Clarity"
ASSETS = ["ShenQing-Setup-{version}.exe", "ShenQing-Portable-v{version}.zip"]


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: make_update_manifest.py <version> [--base-url URL]", file=sys.stderr)
        return 2
    version = argv[0].lstrip("vV")
    base = ""
    if "--base-url" in argv:
        try:
            base = argv[argv.index("--base-url") + 1].rstrip("/")
        except IndexError:
            base = ""
    if not base:
        base = f"https://github.com/{GITHUB_REPO}/releases/download/v{version}"
    assets = []
    for template in ASSETS:
        name = template.format(version=version)
        assets.append({"name": name, "url": f"{base}/{name}"})
    manifest = {
        "version": version,
        "notes": "",
        "assets": assets,
    }
    Path("packaging").mkdir(exist_ok=True)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
