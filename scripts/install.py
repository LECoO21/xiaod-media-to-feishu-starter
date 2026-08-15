#!/usr/bin/env python3
"""Install the credential-free v2 profile for 小D-链接转录助手."""

from __future__ import annotations

import argparse
import os
import platform
import re
import shutil
import subprocess
import sys
import venv
from pathlib import Path
from typing import Optional


PROFILE_NAME = "media-transcriber"
SKILL_NAME = "xiaod-media-to-feishu"
RUNTIME_NAME = "xiaod-media-to-feishu-v2"
MANAGED_MARKER = "# Managed by xiaod-media-to-feishu-v2"
PACKAGES = (
    "yt-dlp==2025.10.14",
    "imageio-ffmpeg==0.6.0",
    "mlx-whisper==0.4.3",
    "youtube-transcript-api==1.2.2",
)
DIST_OWNED = (
    "SOUL.md",
    "config.yaml",
    "distribution.yaml",
    ".env.EXAMPLE",
    "skills",
    "scripts",
)
MIN_LARK_VERSION = (1, 0, 83)


class InstallError(RuntimeError):
    pass


def run(command: list[str], *, env: Optional[dict[str, str]] = None) -> None:
    print("→", " ".join(command))
    completed = subprocess.run(command, env=env, check=False)
    if completed.returncode != 0:
        raise InstallError(f"命令失败，退出码 {completed.returncode}")


def command_version(command: str) -> tuple[int, int, int]:
    completed = subprocess.run([command, "--version"], text=True, capture_output=True)
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", completed.stdout + completed.stderr)
    return tuple(map(int, match.groups())) if match else (0, 0, 0)


def write_managed(path: Path, content: str) -> None:
    if path.exists() and MANAGED_MARKER not in path.read_text(
        encoding="utf-8", errors="ignore"
    ):
        raise InstallError(f"不会覆盖非本安装器管理的文件：{path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def ensure_path(shell_rc: Path) -> None:
    export_line = 'export PATH="$HOME/.local/bin:$PATH"'
    existing = shell_rc.read_text(encoding="utf-8", errors="ignore") if shell_rc.exists() else ""
    if export_line in existing:
        return
    with shell_rc.open("a", encoding="utf-8") as handle:
        handle.write(f"\n{MANAGED_MARKER}\n{export_line}\n")


def install_dependencies(venv_dir: Path) -> Path:
    if not venv_dir.exists():
        print("→ 创建独立媒体运行环境")
        venv.EnvBuilder(with_pip=True).create(venv_dir)
    python = venv_dir / "bin" / "python"
    run([str(python), "-m", "pip", "install", "--upgrade", "pip"])
    run([str(python), "-m", "pip", "install", *PACKAGES])
    completed = subprocess.run(
        [str(python), "-c", "import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())"],
        text=True,
        capture_output=True,
        check=True,
    )
    source = Path(completed.stdout.strip())
    link = venv_dir / "bin" / "ffmpeg"
    if link.is_symlink() and link.resolve() != source.resolve():
        link.unlink()
    if not link.exists():
        link.symlink_to(source)
    return python


def copy_distribution_for_test(package_root: Path, profile_dir: Path) -> None:
    profile_dir.mkdir(parents=True, exist_ok=True)
    for name in DIST_OWNED:
        source = package_root / name
        target = profile_dir / name
        if source.is_dir():
            shutil.copytree(source, target, dirs_exist_ok=True)
        else:
            shutil.copy2(source, target)


def patch_workspace(profile_dir: Path, workspace: Path) -> None:
    config = profile_dir / "config.yaml"
    text = config.read_text(encoding="utf-8")
    if "__XIAOD_WORKSPACE__" in text:
        config.write_text(text.replace("__XIAOD_WORKSPACE__", str(workspace)), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="安装小D-链接转录助手 v2")
    parser.add_argument("--profile", default=PROFILE_NAME)
    parser.add_argument("--home", type=Path, default=Path.home(), help=argparse.SUPPRESS)
    parser.add_argument("--force", action="store_true", help="更新已安装的 v2 Profile")
    parser.add_argument("--no-setup", action="store_true", help="安装后暂不运行首次配置")
    parser.add_argument("--skip-deps", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--skip-profile-install", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()

    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", args.profile):
        raise InstallError("Profile 名称只能包含小写字母、数字和连字符")
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        raise InstallError("当前安装包仅支持 Apple Silicon Mac")

    target_home = args.home.expanduser().resolve()
    package_root = Path(__file__).resolve().parents[1]
    hermes = shutil.which("hermes")
    lark = shutil.which("lark-cli")
    if not hermes and not args.skip_profile_install:
        raise InstallError("未找到 Hermes CLI。请先安装 Hermes，再重新运行。")
    if not lark:
        raise InstallError("未找到飞书 CLI（lark-cli）。请先安装，再重新运行。")
    if command_version(lark) < MIN_LARK_VERSION:
        raise InstallError("飞书 CLI 版本过旧。请升级到 1.0.83 或更高版本。")

    hermes_root = Path(os.environ.get("HERMES_HOME", target_home / ".hermes")).expanduser()
    profile_dir = hermes_root / "profiles" / args.profile
    workspace = target_home / "Documents" / "xiaod-media-workspace"

    if args.skip_profile_install:
        copy_distribution_for_test(package_root, profile_dir)
    else:
        command = [
            hermes or "hermes",
            "profile",
            "install",
            str(package_root),
            "--name",
            args.profile,
            "--alias",
            "--yes",
        ]
        if args.force:
            command.append("--force")
        run(command)

    patch_workspace(profile_dir, workspace)
    for folder in ("incoming", "work", "outputs"):
        (workspace / folder).mkdir(parents=True, exist_ok=True)

    runtime_dir = target_home / ".local" / "share" / RUNTIME_NAME
    venv_dir = runtime_dir / "venv"
    if args.skip_deps:
        if not venv_dir.exists():
            venv.EnvBuilder(with_pip=True).create(venv_dir)
        runtime_python = venv_dir / "bin" / "python"
    else:
        runtime_python = install_dependencies(venv_dir)

    local_bin = target_home / ".local" / "bin"
    local_bin.mkdir(parents=True, exist_ok=True)
    skill_dir = profile_dir / "skills" / SKILL_NAME

    write_managed(
        local_bin / "xiaod-media-pipeline",
        f'''#!/bin/sh
{MANAGED_MARKER}
export PATH="{venv_dir / 'bin'}:$PATH"
exec "{runtime_python}" "{skill_dir / 'scripts' / 'media_pipeline.py'}" "$@"
''',
    )
    write_managed(
        local_bin / "xiaod",
        f'''#!/bin/sh
{MANAGED_MARKER}
profile_name="${{XIAOD_PROFILE:-{args.profile}}}"
workspace_dir="${{XIAOD_WORKSPACE:-$HOME/Documents/xiaod-media-workspace}}"
mkdir -p "$workspace_dir/incoming" "$workspace_dir/work" "$workspace_dir/outputs"
cd "$workspace_dir" || exit 1
exec "{hermes or 'hermes'}" --profile "$profile_name" --skills "{SKILL_NAME}" "$@"
''',
    )
    write_managed(
        local_bin / "xiaod-doctor",
        f'''#!/bin/sh
{MANAGED_MARKER}
export PATH="{local_bin}:{venv_dir / 'bin'}:$PATH"
exec "{runtime_python}" "{profile_dir / 'scripts' / 'doctor.py'}" --profile "${{XIAOD_PROFILE:-{args.profile}}}"
''',
    )
    write_managed(
        local_bin / "xiaod-setup",
        f'''#!/bin/sh
{MANAGED_MARKER}
export PATH="{local_bin}:{venv_dir / 'bin'}:$PATH"
export XIAOD_PROFILE="${{XIAOD_PROFILE:-{args.profile}}}"
export XIAOD_PROFILE_HOME="{profile_dir}"
export XIAOD_ENV_FILE="{profile_dir / '.env'}"
export XIAOD_HERMES_BIN="{hermes or 'hermes'}"
export XIAOD_LARK_CLI="{local_bin / 'lark-cli-user'}"
exec /bin/bash "{profile_dir / 'scripts' / 'setup-wizard.sh'}"
''',
    )
    write_managed(
        local_bin / "lark-cli-user",
        f'''#!/bin/sh
{MANAGED_MARKER}
lark_command="${{XIAOD_LARK_CLI_BIN:-{lark or 'lark-cli'}}}"
lark_bin_dir=$(dirname "$lark_command")
exec /usr/bin/env -i \
  HOME="$HOME" \
  PATH="$lark_bin_dir:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin" \
  TMPDIR="${{TMPDIR:-/tmp}}" \
  LANG="${{LANG:-en_US.UTF-8}}" \
  HTTPS_PROXY="${{HTTPS_PROXY:-}}" \
  HTTP_PROXY="${{HTTP_PROXY:-}}" \
  ALL_PROXY="${{ALL_PROXY:-}}" \
  NO_PROXY="${{NO_PROXY:-}}" \
  "$lark_command" "$@"
''',
    )

    (profile_dir / "scripts" / "setup-wizard.sh").chmod(0o755)
    ensure_path(target_home / ".zshrc")

    print("\n✓ v2 安装完成。未读取、复制或写入任何账号凭据。")
    print("✓ 飞书机器人统一名称：小D-链接转录助手")
    print("✓ GitHub v1 文件保持不变")
    print("\n下一步运行：xiaod-setup")

    if not args.no_setup and sys.stdin.isatty():
        answer = input("\n现在开始首次配置吗？[Y/n] ").strip().lower()
        if answer in ("", "y", "yes"):
            run([str(local_bin / "xiaod-setup")])


if __name__ == "__main__":
    try:
        main()
    except InstallError as exc:
        print(f"\n安装失败：{exc}", file=sys.stderr)
        raise SystemExit(1)
