#!/usr/bin/env python3
"""为选定风格的任意数量 PPT 页面生成带页码标签的总览图。"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys

from PIL import Image, ImageDraw

from build_style_matrix import (
    IMAGE_SUFFIXES,
    TARGET_RATIO,
    choose_font,
    configure_utf8_stdio,
    load_and_validate,
)


def parse_pages(value: str) -> list[str]:
    pages = [item.strip() for item in value.split(",") if item.strip()]
    if not pages:
        raise argparse.ArgumentTypeError("--pages 至少提供一个页面标识")
    if len(set(pages)) != len(pages):
        raise argparse.ArgumentTypeError("--pages 中的页面标识不得重复")
    return pages


def parse_style_id(value: str) -> str:
    style_id = value.strip()
    invalid_chars = '<>:"/\\|?*'
    if (
        not style_id
        or style_id in {".", ".."}
        or style_id.endswith((".", " "))
        or any(char in style_id for char in invalid_chars)
    ):
        raise argparse.ArgumentTypeError("--style-id 不是安全的 Windows 文件名前缀")
    return style_id


def find_page(
    project_dir: Path,
    style_id: str,
    page_id: str,
    source_state: dict | None,
) -> Path:
    if source_state is not None:
        try:
            raw_path = source_state["pages"][page_id]["selected_source"]
        except (KeyError, TypeError) as exc:
            raise FileNotFoundError(f"扩页状态缺少 pages/{page_id}/selected_source") from exc
        if not isinstance(raw_path, str) or not raw_path.strip():
            raise FileNotFoundError(f"扩页状态中的 pages/{page_id} 尚无 selected_source")
        path = Path(raw_path).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"原始图片不存在：{path}")
        return path

    origin_dir = project_dir / "origin_image"
    matches = [
        path
        for path in origin_dir.glob(f"{style_id}_page_{page_id}.*")
        if path.suffix.lower() in IMAGE_SUFFIXES
    ]
    if not matches:
        legacy_folder = origin_dir / style_id
        matches = [
            path
            for path in legacy_folder.glob(f"page_{page_id}.*")
            if path.suffix.lower() in IMAGE_SUFFIXES
        ]
    if len(matches) != 1:
        raise FileNotFoundError(
            f"需要且只能存在一张 {style_id}_page_{page_id} 图片，实际找到 {len(matches)} 张"
        )
    return matches[0]


def default_output(project_dir: Path, style_id: str, pages: list[str]) -> Path:
    page_token = "-".join(pages)
    if len(page_token) > 80:
        page_token = f"{pages[0]}-{pages[-1]}_{len(pages)}pages"
    return project_dir / "overview" / f"{style_id}_{page_token}_overview.png"


def draw_placeholder(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    width: int,
    height: int,
    page_id: str,
    reason: str,
) -> None:
    draw.rectangle((x, y, x + width, y + height), fill="#E4E4E4", outline="#B42318", width=4)
    font = choose_font(max(16, width // 36))
    draw.text((x + 20, y + 20), "缺失或无效，等待定向修复", fill="#7A271A", font=font)
    short_reason = reason if len(reason) <= 80 else reason[:77] + "..."
    draw.text((x + 20, y + 64), f"第 {page_id} 页：{short_reason}", fill="#555555", font=font)


def build_overview(
    project_dir: Path,
    style_id: str,
    pages: list[str],
    output: Path,
    columns: int,
    cell_width: int,
    label_height: int,
    gap: int,
    ratio_tolerance: float,
    source_state: dict | None,
    allow_invalid: bool,
) -> list[str]:
    columns = min(columns, len(pages))
    rows = math.ceil(len(pages) / columns)
    cell_height = round(cell_width / TARGET_RATIO)
    canvas_width = columns * cell_width + (columns + 1) * gap
    canvas_height = rows * (label_height + cell_height) + (rows + 1) * gap
    canvas = Image.new("RGB", (canvas_width, canvas_height), "#F2F2F2")
    draw = ImageDraw.Draw(canvas)
    label_font = choose_font(max(18, label_height // 3))
    invalid_pages: list[str] = []

    for index, page_id in enumerate(pages):
        row, column = divmod(index, columns)
        x = gap + column * (cell_width + gap)
        label_y = gap + row * (label_height + cell_height + gap)
        image_y = label_y + label_height
        label = f"第 {page_id} 页"
        box = draw.textbbox((0, 0), label, font=label_font)
        text_width = box[2] - box[0]
        text_height = box[3] - box[1]
        draw.text(
            (x + (cell_width - text_width) / 2, label_y + (label_height - text_height) / 2),
            label,
            fill="#202020",
            font=label_font,
        )

        try:
            path = find_page(project_dir, style_id, page_id, source_state)
            image = load_and_validate(path, ratio_tolerance)
        except (FileNotFoundError, ValueError, OSError) as exc:
            if not allow_invalid:
                raise
            message = f"page_{page_id}: {exc}"
            invalid_pages.append(message)
            draw_placeholder(draw, x, image_y, cell_width, cell_height, page_id, str(exc))
            continue

        resized = image.resize((cell_width, cell_height), Image.Resampling.LANCZOS)
        canvas.paste(resized, (x, image_y))

    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output, format="PNG", optimize=True)
    print(f"已生成：{output}")
    print(f"尺寸：{canvas.width}x{canvas.height}，页面数：{len(pages)}")
    if invalid_pages:
        print(f"警告：总览包含 {len(invalid_pages)} 个待修复占位页面。", file=sys.stderr)
        for item in invalid_pages:
            print(f"- {item}", file=sys.stderr)
    return invalid_pages


def main() -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-dir", type=Path, required=True, help="包含 origin_image 的项目目录")
    parser.add_argument("--style-id", type=parse_style_id, required=True, help="例如 style_A")
    parser.add_argument("--pages", type=parse_pages, required=True, help="页面标识，逗号分隔，数量不限")
    parser.add_argument("--output", type=Path, help="输出 PNG 路径")
    parser.add_argument(
        "--source-state",
        type=Path,
        help="可选：从 selected_style_run_state.json 的 pages.<ID>.selected_source 读取临时原图",
    )
    parser.add_argument("--columns", type=int, default=3, help="总览列数")
    parser.add_argument("--cell-width", type=int, default=960, help="每个页面在总览中的宽度")
    parser.add_argument("--label-height", type=int, default=72, help="每个页面外部页码标签高度")
    parser.add_argument("--gap", type=int, default=24, help="页面之间的间距")
    parser.add_argument("--ratio-tolerance", type=float, default=0.02, help="16:9 比例允许误差")
    parser.add_argument(
        "--allow-invalid",
        action="store_true",
        help="临时质检模式：缺失或无效图片用占位页面显示；正式总览不要使用",
    )
    args = parser.parse_args()

    project_dir = args.project_dir.resolve()
    output = (args.output or default_output(project_dir, args.style_id, args.pages)).resolve()
    if args.columns < 1 or args.cell_width < 320 or args.label_height < 40 or args.gap < 0:
        parser.error("画布参数过小或无效")
    if not 0 <= args.ratio_tolerance <= 0.2:
        parser.error("--ratio-tolerance 必须在 0 到 0.2 之间")
    if output.suffix.lower() != ".png":
        parser.error("--output 必须使用 .png 扩展名")

    try:
        source_state = None
        if args.source_state:
            with args.source_state.resolve().open("r", encoding="utf-8-sig") as handle:
                source_state = json.load(handle)
        build_overview(
            project_dir=project_dir,
            style_id=args.style_id,
            pages=args.pages,
            output=output,
            columns=args.columns,
            cell_width=args.cell_width,
            label_height=args.label_height,
            gap=args.gap,
            ratio_tolerance=args.ratio_tolerance,
            source_state=source_state,
            allow_invalid=args.allow_invalid,
        )
    except (FileNotFoundError, ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
