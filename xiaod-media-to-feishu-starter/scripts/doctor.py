#!/usr/bin/env python3
"""Credential-safe readiness check for the 小D starter package."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path


def result(label: str, ok: bool, hint: str = "") -> bool:
    mark = "✓" if ok else "✗"
    print(f"{mark} {label}" + (f"：{hint}" if hint else ""))
    return ok


def lark_ready() -> bool:
    command = shutil.which("lark-cli-user") or shutil.which("lark-cli")
    if not command:
        return False
    completed = subprocess.run(
        [command, "auth", "status", "--json", "--verify"],
        text=True,
        capture_output=True,
    )
    if completed.returncode != 0:
        return False
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return False
    return payload.get("ok") is True or payload.get("verified") is True


def pipeline_ready() -> bool:
    command = shutil.which("xiaod-media-pipeline")
    if not command:
        return False
    completed = subprocess.run([command, "doctor"], text=True, capture_output=True)
    if completed.returncode != 0:
        return False
    try:
        return json.loads(completed.stdout).get("ok") is True
    except json.JSONDecodeError:
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description="检查小D是否可以开始工作")
    parser.add_argument("--profile", default="mediatranscriber")
    args = parser.parse_args()

    checks = [
        result("Hermes CLI", shutil.which("hermes") is not None, "缺失时先安装 Hermes"),
        result("本地媒体工具", pipeline_ready(), "失败时重新运行安装器"),
        result("飞书 CLI 与用户登录", lark_ready(), "按飞书 CLI 提示完成登录"),
        result(
            "小D Profile",
            (
                Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
                / "profiles"
                / args.profile
            ).is_dir(),
            "失败时重新运行安装器",
        ),
    ]
    if all(checks):
        print("\n全部就绪。运行 xiaod chat，然后直接发送链接或文件路径。")
        raise SystemExit(0)
    print("\n只处理带 ✗ 的项目；不要把任何密钥或授权链接粘贴到聊天。")
    raise SystemExit(1)


if __name__ == "__main__":
    main()
