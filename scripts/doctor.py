#!/usr/bin/env python3
"""Credential-safe parity checks for 小D-链接转录助手."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Optional


EXPECTED_BOT_NAME = "小D-链接转录助手"
DEFAULT_WIKI_NAME = "音视频转录整理"
MIN_LARK_VERSION = (1, 0, 83)


def run(command: list[str], *, timeout: int = 45) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return subprocess.CompletedProcess(command, 1, "", "")


def mark(label: str, ok: bool, hint: str = "") -> bool:
    print(f"{'✓' if ok else '✗'} {label}" + (f"：{hint}" if not ok and hint else ""))
    return ok


def env_values(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def model_ready(hermes: str, profile: str) -> bool:
    for key in ("model.provider", "model.default"):
        completed = run([hermes, "--profile", profile, "config", "get", key, "--json"])
        if completed.returncode != 0:
            return False
        try:
            value = json.loads(completed.stdout)
        except json.JSONDecodeError:
            return False
        if not isinstance(value, str) or not value.strip():
            return False
    return True


def gateway_ready(hermes: str, profile: str) -> bool:
    completed = run([hermes, "--profile", profile, "gateway", "status", "--deep"])
    signal = (completed.stdout + completed.stderr).lower()
    if any(word in signal for word in ("not running", "stopped", "inactive", "not installed")):
        return False
    return completed.returncode == 0 and bool(
        re.search(r"gateway is running|supervised by|active \(running\)|pid\s+\d+", signal)
    )


def pairing_count(profile_dir: Path) -> int:
    path = profile_dir / "platforms" / "pairing" / "feishu-approved.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    if isinstance(payload, (dict, list)):
        return len(payload)
    return 0


def lark_command() -> Optional[str]:
    return shutil.which("lark-cli-user") or shutil.which("lark-cli")


def lark_version_ready(command: Optional[str]) -> bool:
    if not command:
        return False
    completed = run([command, "--version"])
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", completed.stdout + completed.stderr)
    return bool(match and tuple(map(int, match.groups())) >= MIN_LARK_VERSION)


def lark_user_ready(command: Optional[str]) -> bool:
    if not command:
        return False
    auth = run([command, "auth", "status", "--json", "--verify"])
    if auth.returncode != 0:
        return False
    try:
        payload = json.loads(auth.stdout)
    except json.JSONDecodeError:
        return False
    if payload.get("ok") is not True and payload.get("verified") is not True:
        return False
    whoami = run([command, "whoami", "--as", "user"])
    return whoami.returncode == 0


def wiki_match_count(command: Optional[str], name: str) -> int:
    if not command:
        return -1
    expression = f"[.. | objects | select(.name? == {json.dumps(name, ensure_ascii=False)})] | length"
    completed = run(
        [
            command,
            "wiki",
            "+space-list",
            "--as",
            "user",
            "--page-all",
            "--json",
            "--jq",
            expression,
        ]
    )
    if completed.returncode != 0:
        return -1
    match = re.search(r"(^|\n)\s*(\d+)\s*$", completed.stdout)
    return int(match.group(2)) if match else -1


def pipeline_ready() -> bool:
    command = shutil.which("xiaod-media-pipeline")
    if not command:
        return False
    completed = run([command, "doctor"])
    if completed.returncode != 0:
        return False
    try:
        return json.loads(completed.stdout).get("ok") is True
    except json.JSONDecodeError:
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description="检查小D是否与完整部署要求一致")
    parser.add_argument("--profile", default="media-transcriber")
    args = parser.parse_args()

    hermes = shutil.which("hermes")
    hermes_home = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
    profile_dir = hermes_home / "profiles" / args.profile
    values = env_values(profile_dir / ".env")
    lark = lark_command()
    wiki_name = values.get("XIAOD_WIKI_SPACE_NAME", DEFAULT_WIKI_NAME)
    wiki_count = wiki_match_count(lark, wiki_name) if lark_user_ready(lark) else -1

    checks = [
        mark("Hermes CLI", hermes is not None, "先安装 Hermes 0.20.0 或更高版本"),
        mark(
            "完整 Profile 分发",
            (profile_dir / "distribution.yaml").is_file(),
            "重新运行 v2 安装器",
        ),
        mark("模型服务", bool(hermes and model_ready(hermes, args.profile)), "运行 xiaod-setup"),
        mark("本地媒体工具", pipeline_ready(), "重新运行 v2 安装器"),
        mark(
            "飞书机器人配置",
            bool(values.get("FEISHU_APP_ID") and values.get("FEISHU_APP_SECRET")),
            "运行 xiaod-setup 完成扫码部署",
        ),
        mark(
            f"机器人名称为 {EXPECTED_BOT_NAME}",
            values.get("XIAOD_FEISHU_BOT_NAME") == EXPECTED_BOT_NAME,
            "在飞书开放平台改名、发布后重新运行 xiaod-setup 确认",
        ),
        mark(
            "飞书消息网关",
            bool(hermes and gateway_ready(hermes, args.profile)),
            "运行 xiaod-setup 安装并启动网关",
        ),
        mark(
            "飞书聊天配对",
            pairing_count(profile_dir) > 0,
            "在飞书私聊机器人取得配对码，再运行 xiaod-setup",
        ),
        mark(
            "飞书 CLI 版本与用户授权",
            lark_version_ready(lark) and lark_user_ready(lark),
            "升级飞书 CLI 后运行 xiaod-setup 完成用户授权",
        ),
        mark(
            f"知识库“{wiki_name}”唯一可见",
            wiki_count == 1,
            "运行 xiaod-setup 创建、授权或处理重名知识库",
        ),
    ]

    if all(checks):
        print("\n全部通过。现在可在飞书中与小D聊天，文档交付必须完成入库回读后才会报告成功。")
        raise SystemExit(0)
    print("\n尚未完成部署。只处理带 ✗ 的项目；不要把密钥、Token 或授权链接粘贴到聊天。")
    raise SystemExit(1)


if __name__ == "__main__":
    main()
