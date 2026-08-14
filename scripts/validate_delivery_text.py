#!/usr/bin/env python3
"""Validate that a PPT image handoff stays link-only in the root task."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys


RULES = (
    (
        "markdown_image",
        re.compile(r"!\s*\[", re.IGNORECASE),
        "不得使用 Markdown 图片嵌入；改用普通可点击链接",
    ),
    (
        "html_media",
        re.compile(r"<\s*(?:img|picture|svg|object|embed)\b", re.IGNORECASE),
        "不得使用 HTML 图片或媒体嵌入标签",
    ),
    (
        "image_data_uri",
        re.compile(r"data\s*:\s*image\s*/", re.IGNORECASE),
        "不得包含 image data URI",
    ),
    (
        "base64_marker",
        re.compile(r";\s*base64\s*,", re.IGNORECASE),
        "不得包含 Base64 内嵌载荷",
    ),
    (
        "known_image_base64",
        re.compile(
            r"(?:iVBORw0KGgo[A-Za-z0-9+/=]{24,}|"
            r"/9j/[A-Za-z0-9+/=]{24,}|"
            r"R0lGOD(?:lh|dh)[A-Za-z0-9+/=]{24,}|"
            r"UklGR[A-Za-z0-9+/=]{24,})"
        ),
        "不得包含图片 Base64 载荷",
    ),
    (
        "long_base64_blob",
        re.compile(r"(?<![A-Za-z0-9+/=])[A-Za-z0-9+/]{512,}={0,2}(?![A-Za-z0-9+/=])"),
        "不得包含超长裸 Base64 载荷",
    ),
)

ORDINARY_LINK = re.compile(r"(?<!!)\[[^\]\n]+\]\((?:<[^>\n]+>|[^)\n]+)\)")
ORDINARY_LINK_CAPTURE = re.compile(
    r"(?<!!)\[([^\]\n]+)\]\((?:<([^>\n]+)>|([^)\n]+))\)"
)


def location(text: str, offset: int) -> tuple[int, int]:
    line = text.count("\n", 0, offset) + 1
    last_newline = text.rfind("\n", 0, offset)
    column = offset + 1 if last_newline < 0 else offset - last_newline
    return line, column


def validate_fast8_links_only(
    text: str, project_dir: Path | None = None
) -> list[dict[str, object]]:
    """Require a compact two-line overview-plus-A-H link-only message."""

    violations: list[dict[str, object]] = []
    matches = list(ORDINARY_LINK_CAPTURE.finditer(text))
    residual = ORDINARY_LINK_CAPTURE.sub("", text).strip()
    if residual:
        violations.append(
            {
                "rule": "fast8_extra_delivery_text",
                "line": 1,
                "column": 1,
                "message": "Fast8 交付只允许总览与 A-H 九个普通链接，不得附加状态、耗时、报告或说明文字",
            }
        )
    lines = text.splitlines()
    line_matches = [list(ORDINARY_LINK_CAPTURE.finditer(line)) for line in lines]
    if (
        len(lines) != 2
        or not lines[0].strip()
        or not lines[1].strip()
        or len(line_matches[0]) != 1
        or len(line_matches[1]) != 8
    ):
        violations.append(
            {
                "rule": "fast8_delivery_line_structure",
                "line": 1,
                "column": 1,
                "message": "Fast8 交付必须是两行：第一行总览，第二行合并 A-H 八张图片链接",
            }
        )
    expected_labels = ["总览", *list("ABCDEFGH")]
    actual_labels = [match.group(1).strip() for match in matches]
    if actual_labels != expected_labels:
        violations.append(
            {
                "rule": "fast8_link_labels_or_order",
                "line": 1,
                "column": 1,
                "message": "Fast8 链接必须严格按 总览、A、B、C、D、E、F、G、H 排列",
            }
        )
        return violations

    root = project_dir.resolve() if project_dir is not None else None
    for index, match in enumerate(matches):
        raw_target = (match.group(2) or match.group(3) or "").strip()
        target = Path(raw_target).expanduser()
        if not target.is_absolute():
            violations.append(
                {
                    "rule": "fast8_link_not_absolute",
                    "line": location(text, match.start())[0],
                    "column": 1,
                    "message": f"Fast8 {expected_labels[index]} 链接必须使用绝对路径",
                }
            )
            continue
        resolved = target.resolve()
        if root is not None:
            try:
                resolved.relative_to(root)
            except ValueError:
                violations.append(
                    {
                        "rule": "fast8_link_outside_project",
                        "line": location(text, match.start())[0],
                        "column": 1,
                        "message": f"Fast8 {expected_labels[index]} 链接必须位于当前 project_dir 内",
                    }
                )
        if index == 0:
            if (
                resolved.name not in {"ABCDEFGH_2x4.png", "ABCDEFGH_4x2.png"}
                or resolved.parent.name != "overview"
            ):
                violations.append(
                    {
                        "rule": "fast8_overview_link_invalid",
                        "line": location(text, match.start())[0],
                        "column": 1,
                        "message": (
                            "总览链接必须指向新布局 overview/ABCDEFGH_2x4.png；"
                            "历史任务允许 ABCDEFGH_4x2.png"
                        ),
                    }
                )
        else:
            style = expected_labels[index]
            if (
                resolved.parent.name != "origin_image"
                or re.fullmatch(
                    rf"style_{style}_page_.+\.(?:png|jpg|jpeg|webp)",
                    resolved.name,
                    re.IGNORECASE,
                )
                is None
            ):
                violations.append(
                    {
                        "rule": "fast8_candidate_link_invalid",
                        "line": location(text, match.start())[0],
                        "column": 1,
                        "message": f"{style} 链接必须指向 origin_image/style_{style}_page_* 图片",
                    }
                )
    return violations


def validate_text(
    text: str,
    require_link: bool = False,
    fast8_links_only: bool = False,
    project_dir: Path | None = None,
) -> list[dict[str, object]]:
    violations: list[dict[str, object]] = []
    for rule, pattern, message in RULES:
        match = pattern.search(text)
        if match:
            line, column = location(text, match.start())
            violations.append(
                {
                    "rule": rule,
                    "line": line,
                    "column": column,
                    "message": message,
                }
            )
    if require_link and not ORDINARY_LINK.search(text):
        violations.append(
            {
                "rule": "missing_ordinary_link",
                "line": 1,
                "column": 1,
                "message": "成功交付必须至少包含一个普通可点击文件链接",
            }
        )
    if fast8_links_only:
        violations.extend(validate_fast8_links_only(text, project_dir=project_dir))
    return violations


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", required=True, help="待逐字发送的 UTF-8 交付草稿")
    parser.add_argument(
        "--require-link",
        action="store_true",
        help="要求草稿至少包含一个普通 Markdown 链接",
    )
    parser.add_argument(
        "--fast8-links-only",
        action="store_true",
        help="要求草稿严格只包含总览与 A-H 九个普通链接",
    )
    parser.add_argument(
        "--project-dir",
        help="与 --fast8-links-only 配合，要求九个链接都位于当前任务目录",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    path = Path(args.file).resolve()
    try:
        payload = path.read_bytes()
        text = payload.decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        print(
            json.dumps(
                {"status": "error", "error": f"无法读取 UTF-8 草稿：{exc}"},
                ensure_ascii=False,
            )
        )
        raise SystemExit(1) from exc

    project_dir = Path(args.project_dir).resolve() if args.project_dir else None
    violations = validate_text(
        text,
        require_link=args.require_link,
        fast8_links_only=args.fast8_links_only,
        project_dir=project_dir,
    )
    result = {
        "status": "pass" if not violations else "fail",
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "violations": violations,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if violations:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
