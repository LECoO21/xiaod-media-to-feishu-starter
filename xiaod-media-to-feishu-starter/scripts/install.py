#!/usr/bin/env python3
"""Install the portable 小D skill without copying credentials or account data."""

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


SKILL_NAME = "xiaod-media-to-feishu-starter"
DEFAULT_PROFILE = "mediatranscriber"
MANAGED_MARKER = "# Managed by xiaod-media-to-feishu-starter"
PACKAGES = (
    "yt-dlp>=2026.7.4",
    "imageio-ffmpeg>=0.6.0",
    "mlx-whisper>=0.4.3",
    "youtube-transcript-api>=1.2.2",
)


class InstallError(RuntimeError):
    pass


def run(command: list[str], *, env: Optional[dict[str, str]] = None) -> None:
    print("→", " ".join(command))
    completed = subprocess.run(command, env=env)
    if completed.returncode != 0:
        raise InstallError(f"Command failed with exit code {completed.returncode}")


def write_managed(path: Path, content: str) -> None:
    if path.exists() and MANAGED_MARKER not in path.read_text(encoding="utf-8", errors="ignore"):
        raise InstallError(f"Refusing to overwrite an unmanaged file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def ensure_path(shell_rc: Path) -> None:
    export_line = 'export PATH="$HOME/.local/bin:$PATH"'
    if shell_rc.exists() and export_line in shell_rc.read_text(encoding="utf-8", errors="ignore"):
        return
    with shell_rc.open("a", encoding="utf-8") as handle:
        handle.write(f"\n{MANAGED_MARKER}\n{export_line}\n")


def ensure_skill_loaded(config_path: Path) -> None:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    text = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
    item = f"    - {SKILL_NAME}"
    if item in text:
        return
    lines = text.splitlines()
    skills_index = next((index for index, line in enumerate(lines) if line == "skills:"), None)
    if skills_index is None:
        if lines and lines[-1].strip():
            lines.append("")
        lines.extend(["skills:", "  always_load:", item])
    else:
        block_end = len(lines)
        for index in range(skills_index + 1, len(lines)):
            if lines[index] and not lines[index].startswith((" ", "\t")):
                block_end = index
                break
        always_index = next(
            (
                index
                for index in range(skills_index + 1, block_end)
                if lines[index].strip() == "always_load:"
            ),
            None,
        )
        if always_index is None:
            lines[skills_index + 1 : skills_index + 1] = ["  always_load:", item]
        else:
            insert_at = always_index + 1
            while insert_at < block_end and lines[insert_at].startswith("    "):
                insert_at += 1
            lines.insert(insert_at, item)
    config_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def install_dependencies(venv_dir: Path) -> Path:
    if not venv_dir.exists():
        print("→ 创建独立运行环境")
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
    ffmpeg_source = Path(completed.stdout.strip())
    ffmpeg_link = venv_dir / "bin" / "ffmpeg"
    if not ffmpeg_link.exists():
        ffmpeg_link.symlink_to(ffmpeg_source)
    return python


def copy_skill(package_root: Path, destination: Path, *, force: bool) -> None:
    if destination.exists() and not force:
        raise InstallError(f"Skill already exists: {destination}. Re-run with --force to update it.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        package_root,
        destination,
        dirs_exist_ok=force,
        ignore=shutil.ignore_patterns(".DS_Store", "__pycache__", "*.pyc"),
    )


def create_profile(hermes: str, profile: str, profile_dir: Path, *, skip: bool) -> None:
    if profile_dir.exists():
        return
    if skip:
        profile_dir.mkdir(parents=True, exist_ok=True)
        return
    run(
        [
            hermes,
            "profile",
            "create",
            profile,
            "--no-skills",
            "--no-alias",
            "--description",
            "把音视频、逐字稿和飞书内容整理成交付文档。",
        ]
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="安装小D链接转文档小白版")
    parser.add_argument("--profile", default=DEFAULT_PROFILE)
    parser.add_argument("--home", type=Path, default=Path.home(), help=argparse.SUPPRESS)
    parser.add_argument("--force", action="store_true", help="更新已安装的同名 Skill")
    parser.add_argument("--skip-deps", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--skip-profile-create", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()

    if not re.fullmatch(r"[a-z0-9]+", args.profile):
        raise InstallError("Profile 名称只能包含小写字母和数字")
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        raise InstallError("当前安装包仅支持 Apple Silicon Mac")

    target_home = args.home.expanduser().resolve()
    hermes = shutil.which("hermes")
    if not hermes and not args.skip_profile_create:
        raise InstallError("未找到 Hermes CLI。请先安装 Hermes，再重新运行本安装器。")

    package_root = Path(__file__).resolve().parents[1]
    hermes_home = Path(os.environ.get("HERMES_HOME", target_home / ".hermes")).expanduser()
    profile_dir = hermes_home / "profiles" / args.profile
    create_profile(hermes or "hermes", args.profile, profile_dir, skip=args.skip_profile_create)

    runtime_dir = target_home / ".local" / "share" / SKILL_NAME
    venv_dir = runtime_dir / "venv"
    if args.skip_deps:
        if not venv_dir.exists():
            venv.EnvBuilder(with_pip=True).create(venv_dir)
        runtime_python = venv_dir / "bin" / "python"
    else:
        runtime_python = install_dependencies(venv_dir)

    installed_skill = profile_dir / "skills" / SKILL_NAME
    copy_skill(package_root, installed_skill, force=args.force)
    ensure_skill_loaded(profile_dir / "config.yaml")

    soul = profile_dir / "SOUL.md"
    if not soul.exists():
        soul.write_text(
            "# 小D：链接转文档\n\n"
            "只使用 xiaod-media-to-feishu-starter Skill。把公开音视频、用户有权访问的"
            "飞书内容和本地媒体整理成分享式中文长稿，完成质检、飞书入库、访问验证和"
            "中间文件清理。不得绕过访问控制，不得读取、输出或保存任何凭据。\n",
            encoding="utf-8",
        )

    workspace = target_home / "Documents" / "xiaod-media-workspace"
    for folder in ("incoming", "work", "outputs"):
        (workspace / folder).mkdir(parents=True, exist_ok=True)

    local_bin = target_home / ".local" / "bin"
    local_bin.mkdir(parents=True, exist_ok=True)
    write_managed(
        local_bin / "xiaod-media-pipeline",
        f'''#!/bin/sh
{MANAGED_MARKER}
export PATH="{venv_dir / 'bin'}:$PATH"
exec "{runtime_python}" "{installed_skill / 'scripts' / 'media_pipeline.py'}" "$@"
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
exec "{runtime_python}" "{installed_skill / 'scripts' / 'doctor.py'}" --profile "${{XIAOD_PROFILE:-{args.profile}}}"
''',
    )

    lark_wrapper = local_bin / "lark-cli-user"
    if not lark_wrapper.exists():
        write_managed(
            lark_wrapper,
            '''#!/bin/sh
# Managed by xiaod-media-to-feishu-starter
lark_command="${XIAOD_LARK_CLI:-$(command -v lark-cli)}"
if [ -z "$lark_command" ]; then
  echo "未找到飞书 CLI，请先安装并完成登录。" >&2
  exit 1
fi
lark_bin_dir=$(dirname "$lark_command")
exec /usr/bin/env -i \
  HOME="$HOME" \
  PATH="$lark_bin_dir:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin" \
  TMPDIR="${TMPDIR:-/tmp}" \
  LANG="${LANG:-en_US.UTF-8}" \
  HTTPS_PROXY="${HTTPS_PROXY:-}" \
  HTTP_PROXY="${HTTP_PROXY:-}" \
  ALL_PROXY="${ALL_PROXY:-}" \
  NO_PROXY="${NO_PROXY:-}" \
  "$lark_command" "$@"
''',
        )

    ensure_path(target_home / ".zshrc")

    print("\n✓ 小D安装完成，安装包没有读取或复制任何凭据。")
    print("\n接下来只需：")
    print("1. 重新打开终端，运行：xiaod setup（配置模型服务）")
    print("2. 按飞书 CLI 自带提示完成登录")
    print("3. 运行：xiaod-doctor")
    print("4. 全部通过后运行：xiaod chat")


if __name__ == "__main__":
    try:
        main()
    except (InstallError, OSError, subprocess.SubprocessError) as exc:
        print(f"安装失败：{exc}", file=sys.stderr)
        raise SystemExit(1)
