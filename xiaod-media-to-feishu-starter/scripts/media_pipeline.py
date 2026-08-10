#!/usr/bin/env python3
"""Portable, credential-free media intake and transcription helpers for 小D."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, urlparse


DEFAULT_MODEL = os.environ.get(
    "MEDIA_TRANSCRIBER_MODEL",
    "mlx-community/whisper-large-v3-turbo-q4",
)
DEFAULT_SUB_LANGS = "zh-Hans,zh-Hant,zh.*,en.*"
WIKI_URL_RE = re.compile(r"^https://[A-Za-z0-9.-]+/(?:wiki)/[A-Za-z0-9]+(?:[/?#].*)?$")
RESERVED_JOB_DIR_NAMES = {"source", "JOB"}


class PipelineError(RuntimeError):
    pass


def emit(payload: dict, exit_code: int = 0) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    raise SystemExit(exit_code)


def require_bin(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise PipelineError(f"Required command is not on PATH: {name}")
    return path


def find_lark_cli(*, required: bool = False) -> Optional[str]:
    configured = os.environ.get("XIAOD_LARK_CLI", "").strip()
    candidates = [configured, shutil.which("lark-cli-user"), shutil.which("lark-cli")]
    path = next((item for item in candidates if item and os.access(item, os.X_OK)), None)
    if required and not path:
        raise PipelineError(
            "Feishu CLI is not configured. Run the package setup steps; local files were preserved."
        )
    return path


def run(cmd: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(cmd, text=True, capture_output=True)
    if check and completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "unknown error").strip()
        lowered = detail.lower()
        if "cookies-from-browser" in lowered or "confirm you’re not a bot" in lowered or "confirm you're not a bot" in lowered:
            detail = (
                "The platform requires login or anti-bot verification. This profile intentionally does not load "
                "browser cookies. Try an official transcript/API, or provide a local media export you are authorized to use."
            )
        raise PipelineError(f"Command failed ({completed.returncode}): {detail[-5000:]}")
    return completed


def is_url(value: str) -> bool:
    return urlparse(value).scheme in {"http", "https"}


def existing_file(value: str) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise PipelineError(f"Local media file does not exist: {path}")
    return path


def command_version(name: str, args: list[str]) -> dict:
    path = shutil.which(name)
    if not path:
        return {"available": False}
    completed = run([path, *args], check=False)
    text = (completed.stdout or completed.stderr).strip().splitlines()
    return {"available": completed.returncode == 0, "path": path, "version": text[0] if text else "unknown"}


def doctor(_: argparse.Namespace) -> None:
    try:
        mlx_version = importlib.metadata.version("mlx-whisper")
    except importlib.metadata.PackageNotFoundError:
        mlx_version = None
    lark_cli = find_lark_cli()
    emit(
        {
            "ok": all(shutil.which(name) for name in ("yt-dlp", "ffmpeg")) and bool(lark_cli) and mlx_version is not None,
            "tools": {
                "yt-dlp": command_version("yt-dlp", ["--version"]),
                "ffmpeg": command_version("ffmpeg", ["-version"]),
                "lark-cli": command_version(lark_cli, ["--version"]) if lark_cli else {"available": False},
                "mlx-whisper": {"available": mlx_version is not None, "version": mlx_version},
            },
            "note": "This check never reads or prints credentials.",
        }
    )


def inspect_source(args: argparse.Namespace) -> None:
    source = args.source
    if is_url(source):
        yt_dlp = require_bin("yt-dlp")
        completed = run([yt_dlp, "--dump-single-json", "--skip-download", "--no-playlist", "--no-warnings", source])
        data = json.loads(completed.stdout)
        subtitles = sorted((data.get("subtitles") or {}).keys())
        automatic = sorted((data.get("automatic_captions") or {}).keys())
        emit(
            {
                "ok": True,
                "kind": "url",
                "source": source,
                "extractor": data.get("extractor_key") or data.get("extractor"),
                "id": data.get("id"),
                "title": data.get("title"),
                "duration_seconds": data.get("duration"),
                "uploader": data.get("uploader") or data.get("channel"),
                "description": data.get("description"),
                "chapters": data.get("chapters") or [],
                "manual_subtitle_languages": subtitles,
                "automatic_caption_languages": automatic,
            }
        )

    path = existing_file(source)
    ffmpeg = require_bin("ffmpeg")
    completed = run([ffmpeg, "-hide_banner", "-i", str(path)], check=False)
    probe = (completed.stderr or completed.stdout).strip()
    emit(
        {
            "ok": "Invalid data found" not in probe and "No such file" not in probe,
            "kind": "local_file",
            "path": str(path),
            "size_bytes": path.stat().st_size,
            "ffmpeg_probe": probe[-8000:],
        }
    )


def output_dir(value: str) -> Path:
    path = Path(value).expanduser().resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def subtitle_args(source: str, destination: Path, languages: str) -> list[str]:
    ffmpeg = require_bin("ffmpeg")
    return [
        require_bin("yt-dlp"),
        "--no-playlist",
        "--no-warnings",
        "--no-overwrites",
        "--skip-download",
        "--write-info-json",
        "--write-description",
        "--write-subs",
        "--write-auto-subs",
        "--sub-langs",
        languages,
        "--sub-format",
        "vtt",
        "--convert-subs",
        "vtt",
        "--ffmpeg-location",
        str(Path(ffmpeg).parent),
        "-o",
        str(destination / "%(title).120B [%(id)s].%(ext)s"),
        source,
    ]


def subtitles(args: argparse.Namespace) -> None:
    if not is_url(args.url):
        raise PipelineError("subtitles requires an http(s) URL")
    destination = output_dir(args.output_dir)
    before = {p.resolve() for p in destination.iterdir()}
    run(subtitle_args(args.url, destination, args.languages))
    after = {p.resolve() for p in destination.iterdir()}
    created = sorted(str(p) for p in after - before)
    subtitle_files = sorted(
        str(p) for p in after if p.suffix.lower() in {".vtt", ".srt", ".ass", ".ttml"}
    )
    emit({"ok": bool(subtitle_files), "output_dir": str(destination), "subtitle_files": subtitle_files, "created": created})


def youtube_video_id(value: str) -> str:
    parsed = urlparse(value)
    host = parsed.netloc.lower().split(":")[0]
    if host in {"youtu.be", "www.youtu.be"}:
        candidate = parsed.path.strip("/").split("/")[0]
    elif host.endswith("youtube.com"):
        if parsed.path == "/watch":
            candidate = (parse_qs(parsed.query).get("v") or [""])[0]
        elif parsed.path.startswith(("/shorts/", "/embed/", "/live/")):
            candidate = parsed.path.strip("/").split("/")[1]
        else:
            candidate = ""
    else:
        candidate = value if re.fullmatch(r"[A-Za-z0-9_-]{11}", value) else ""
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", candidate):
        raise PipelineError("Could not parse a YouTube video ID")
    return candidate


def youtube_transcript(args: argparse.Namespace) -> None:
    from youtube_transcript_api import YouTubeTranscriptApi

    video_id = youtube_video_id(args.url)
    languages = [item.strip() for item in args.languages.split(",") if item.strip()]
    try:
        fetched = YouTubeTranscriptApi().fetch(video_id, languages=languages)
    except Exception as exc:
        raise PipelineError(f"YouTube transcript is unavailable: {exc}") from exc
    segments = [
        {"text": item.text, "start": item.start, "duration": item.duration}
        for item in fetched
        if item.text and item.text.strip()
    ]
    if not segments:
        raise PipelineError("YouTube returned an empty transcript")
    destination = output_dir(args.output_dir)
    json_path = destination / "source-transcript.json"
    text_path = destination / "source-transcript.txt"
    if (json_path.exists() or text_path.exists()) and not args.force:
        raise PipelineError("Source transcript already exists; use a new job directory or pass --force after preserving it")
    payload = {"video_id": video_id, "language": getattr(fetched, "language_code", None), "segments": segments}
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    text_path.write_text("\n".join(item["text"].strip() for item in segments) + "\n", encoding="utf-8")
    emit({"ok": True, "video_id": video_id, "segments": len(segments), "text": str(text_path), "json": str(json_path)})


def download(args: argparse.Namespace) -> None:
    if not is_url(args.url):
        raise PipelineError("download requires an http(s) URL")
    destination = output_dir(args.output_dir)
    ffmpeg = require_bin("ffmpeg")
    cmd = [
        require_bin("yt-dlp"),
        "--no-playlist",
        "--no-warnings",
        "--no-overwrites",
        "--write-info-json",
        "--write-description",
        "--write-subs",
        "--write-auto-subs",
        "--sub-langs",
        args.languages,
        "--sub-format",
        "vtt",
        "--convert-subs",
        "vtt",
        "--extract-audio",
        "--audio-format",
        args.audio_format,
        "--audio-quality",
        "0",
        "--embed-metadata",
        "--ffmpeg-location",
        str(Path(ffmpeg).parent),
        "--print",
        "after_move:filepath",
        "-o",
        str(destination / "%(title).120B [%(id)s].%(ext)s"),
        args.url,
    ]
    completed = run(cmd)
    candidates = [Path(line.strip()).expanduser() for line in completed.stdout.splitlines() if line.strip()]
    media = next((p.resolve() for p in reversed(candidates) if p.exists()), None)
    emit({"ok": media is not None, "output_dir": str(destination), "media": str(media) if media else None})


def convert(args: argparse.Namespace) -> None:
    source = existing_file(args.input)
    destination = Path(args.output).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and not args.force:
        raise PipelineError("Converted output already exists; use a new path or pass --force after preserving it")
    run(
        [
            require_bin("ffmpeg"),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(source),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "pcm_s16le",
            str(destination),
        ]
    )
    emit({"ok": destination.is_file() and destination.stat().st_size > 0, "input": str(source), "output": str(destination)})


def transcribe(args: argparse.Namespace) -> None:
    source = existing_file(args.input)
    destination = output_dir(args.output_dir)
    text_path = destination / "raw-transcript.txt"
    json_path = destination / "raw-transcript.json"
    if (text_path.exists() or json_path.exists()) and not args.force:
        raise PipelineError("Raw transcript already exists; pass --force only after preserving the previous result")

    import mlx_whisper

    kwargs: dict = {"path_or_hf_repo": args.model, "task": "transcribe"}
    if args.language.lower() != "auto":
        kwargs["language"] = args.language
    if args.initial_prompt:
        kwargs["initial_prompt"] = args.initial_prompt
    try:
        result = mlx_whisper.transcribe(str(source), **kwargs)
    except Exception as exc:
        raise PipelineError(f"mlx-whisper transcription failed: {exc}") from exc
    segment_lines = [
        (segment.get("text") or "").strip()
        for segment in (result.get("segments") or [])
        if (segment.get("text") or "").strip()
    ]
    raw_text = "\n".join(segment_lines) or (result.get("text") or "").strip()
    if not raw_text:
        raise PipelineError("ASR completed without usable text")
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    text_path.write_text(raw_text + "\n", encoding="utf-8")
    emit(
        {
            "ok": True,
            "input": str(source),
            "model": args.model,
            "language": result.get("language") or args.language,
            "text": str(text_path),
            "json": str(json_path),
            "segments": len(result.get("segments") or []),
        }
    )


TIMESTAMP_RE = re.compile(r"(?m)^\s*(?:\[|\()?\d{1,2}:\d{2}(?::\d{2})?(?:\]|\))?\s*")
SPEAKER_RE = re.compile(r"(?mi)^\s*(?:说话人|发言人|主持人|嘉宾|speaker)\s*[\w一二三四五六七八九十.-]*\s*[:：]")
NOISE_RE = re.compile(r"(?i)\[(?:音乐|掌声|笑声|噪音|听不清|music|applause|inaudible|noise)[^\]]*\]")
BANNED_HEADINGS = {"其他有效观点", "补充说明", "核心要点", "一句话总结", "启发", "结论"}


def qc_report(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    headings = [match.group(1).strip().strip("#").strip() for match in re.finditer(r"(?m)^#{1,6}\s+(.+?)\s*$", text)]
    banned = [heading for heading in headings if heading.rstrip("：:") in BANNED_HEADINGS]
    checks = {
        "timestamp_markers": len(TIMESTAMP_RE.findall(text)),
        "speaker_labels": len(SPEAKER_RE.findall(text)),
        "noise_markers": len(NOISE_RE.findall(text)),
        "replacement_characters": text.count("�"),
        "banned_headings": banned,
        "heading_count": len(headings),
        "headings_per_1000_characters": round(len(headings) * 1000 / max(len(text), 1), 2),
        "characters": len(text),
    }
    issues = []
    if checks["timestamp_markers"]:
        issues.append("仍含时间戳")
    if checks["speaker_labels"]:
        issues.append("仍含说话人标签")
    if checks["noise_markers"]:
        issues.append("仍含转录噪音标记")
    if checks["replacement_characters"]:
        issues.append("含 Unicode 替换字符，可能存在乱码")
    if banned:
        issues.append("含摘要式或垃圾桶标题")
    if not headings:
        issues.append("没有可验证的标题结构")
    if len(text) >= 2000 and len(headings) > max(12, len(text) // 500):
        issues.append("标题密度过高，正文可能被过度切碎")
    return {"ok": not issues, "file": str(path), "checks": checks, "issues": issues}


def qc(args: argparse.Namespace) -> None:
    emit(qc_report(existing_file(args.markdown)))


def directory_stats(path: Path) -> tuple[int, int]:
    file_count = 0
    total_bytes = 0
    for item in path.rglob("*"):
        if item.is_file() and not item.is_symlink():
            file_count += 1
            total_bytes += item.stat().st_size
    return file_count, total_bytes


def validate_cleanup_target(value: str) -> tuple[Path, Path]:
    unresolved = Path(value).expanduser().absolute()
    if unresolved.is_symlink() or unresolved.parent.is_symlink():
        raise PipelineError("Cleanup target and its work/ parent must not be symlinks")
    target = unresolved.resolve()
    if not target.is_dir():
        raise PipelineError(f"Cleanup target is not a directory: {target}")
    if target.name in RESERVED_JOB_DIR_NAMES:
        raise PipelineError("Cleanup refuses legacy/shared directory names; inspect and remove their files individually")
    work_root = target.parent
    if work_root.name != "work" or target == work_root or target.parent.parent == target:
        raise PipelineError("Cleanup target must be one direct child directory of a workspace work/ directory")
    if work_root.is_symlink():
        raise PipelineError("Workspace work/ directory must not be a symlink")
    return target, work_root.parent


def validate_wiki_access(wiki_url: str) -> None:
    if not WIKI_URL_RE.fullmatch(wiki_url):
        raise PipelineError("--wiki-url must be a complete Feishu Wiki URL")
    lark_cli = find_lark_cli(required=True)
    completed = subprocess.run(
        [
            str(lark_cli),
            "docs",
            "+fetch",
            "--as",
            "user",
            "--doc",
            wiki_url,
            "--scope",
            "outline",
            "--max-depth",
            "3",
            "--doc-format",
            "markdown",
        ],
        text=True,
        capture_output=True,
    )
    try:
        payload = json.loads(completed.stdout)
        document = payload.get("data", {}).get("document", {})
        content = document.get("content", "")
    except (json.JSONDecodeError, AttributeError):
        payload = {}
        content = ""
    if completed.returncode != 0 or payload.get("ok") is not True or not str(content).strip():
        raise PipelineError("Feishu Wiki outline/access verification failed; local files were preserved")


def cleanup(args: argparse.Namespace) -> None:
    target, workspace = validate_cleanup_target(args.job_dir)
    output = existing_file(args.output)
    outputs_root = (workspace / "outputs").resolve()
    try:
        output.relative_to(outputs_root)
    except ValueError as exc:
        raise PipelineError(f"Final Markdown must be inside {outputs_root}") from exc

    report = qc_report(output)
    if not report["ok"]:
        raise PipelineError(f"Final Markdown failed QC: {', '.join(report['issues'])}")

    validate_wiki_access(args.wiki_url)
    file_count, total_bytes = directory_stats(target)
    payload = {
        "ok": True,
        "mode": "apply" if args.apply else "dry-run",
        "target": str(target),
        "files": file_count,
        "bytes": total_bytes,
        "kept_output": str(output),
        "verified_wiki_url": args.wiki_url,
    }
    if not args.apply:
        payload["note"] = "No files were deleted. Re-run with --apply after reviewing this target."
        emit(payload)

    shutil.rmtree(target)
    payload["deleted"] = not target.exists()
    emit(payload)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Credential-free media transcription helpers")
    subparsers = parser.add_subparsers(dest="command", required=True)

    command = subparsers.add_parser("doctor", help="check installed tools without reading credentials")
    command.set_defaults(func=doctor)

    command = subparsers.add_parser("inspect", help="inspect a URL or local media file")
    command.add_argument("source")
    command.set_defaults(func=inspect_source)

    command = subparsers.add_parser("subtitles", help="download available subtitles without media")
    command.add_argument("url")
    command.add_argument("--output-dir", required=True)
    command.add_argument("--languages", default=DEFAULT_SUB_LANGS)
    command.set_defaults(func=subtitles)

    command = subparsers.add_parser("youtube-transcript", help="fetch a YouTube transcript through its transcript API")
    command.add_argument("url")
    command.add_argument("--output-dir", required=True)
    command.add_argument("--languages", default="zh-Hans,zh-Hant,zh,en")
    command.add_argument("--force", action="store_true")
    command.set_defaults(func=youtube_transcript)

    command = subparsers.add_parser("download", help="download public audio plus metadata and available subtitles")
    command.add_argument("url")
    command.add_argument("--output-dir", required=True)
    command.add_argument("--languages", default=DEFAULT_SUB_LANGS)
    command.add_argument("--audio-format", choices=("m4a", "mp3", "wav", "opus", "flac"), default="m4a")
    command.set_defaults(func=download)

    command = subparsers.add_parser("convert", help="convert local media to 16 kHz mono WAV")
    command.add_argument("input")
    command.add_argument("--output", required=True)
    command.add_argument("--force", action="store_true")
    command.set_defaults(func=convert)

    command = subparsers.add_parser("transcribe", help="transcribe local media with mlx-whisper")
    command.add_argument("input")
    command.add_argument("--output-dir", required=True)
    command.add_argument("--language", default="zh", help="language code, or auto")
    command.add_argument("--model", default=DEFAULT_MODEL)
    command.add_argument("--initial-prompt", default="", help="verified terminology only")
    command.add_argument("--force", action="store_true")
    command.set_defaults(func=transcribe)

    command = subparsers.add_parser("qc", help="run structural checks on a distilled Markdown draft")
    command.add_argument("markdown")
    command.set_defaults(func=qc)

    command = subparsers.add_parser(
        "cleanup",
        help="delete one completed job directory after local QC and live Feishu Wiki verification",
    )
    command.add_argument("job_dir", help="one direct child directory of workspace work/")
    command.add_argument("--output", required=True, help="final Markdown kept under workspace outputs/")
    command.add_argument("--wiki-url", required=True, help="verified Feishu Wiki URL for the delivered document")
    command.add_argument("--apply", action="store_true", help="delete after checks; default is dry-run")
    command.set_defaults(func=cleanup)
    return parser


def main() -> None:
    try:
        args = build_parser().parse_args()
        args.func(args)
    except (PipelineError, OSError, ValueError, json.JSONDecodeError) as exc:
        emit({"ok": False, "error": type(exc).__name__, "message": str(exc)}, exit_code=1)


if __name__ == "__main__":
    main()
