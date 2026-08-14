#!/usr/bin/env python3
"""把 PPT 风格候选拼成 A-H 两列四行快速总览或 A-D 四列完整 4x3 总览图。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError as exc:  # pragma: no cover - environment-specific error path
    raise SystemExit("缺少 Pillow。请在当前 Python 环境安装 pillow 后重试。") from exc


FULL_STYLES = ("A", "B", "C", "D")
QUICK_STYLES = ("A", "B", "C", "D", "E", "F", "G", "H")
TARGET_RATIO = 16 / 9
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


def configure_utf8_stdio() -> None:
    """在 Windows 管道环境中稳定输出中文。"""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


def parse_pages(value: str) -> list[str]:
    pages = [item.strip() for item in value.split(",") if item.strip()]
    if len(pages) not in {1, 3} or len(set(pages)) != len(pages):
        raise argparse.ArgumentTypeError("--pages 必须提供一个或三个不同页面标识，例如 02 或 02,05,08")
    return pages


def parse_styles(value: str) -> list[str]:
    styles = [item.strip().upper().removeprefix("STYLE_") for item in value.split(",") if item.strip()]
    if not styles or len(set(styles)) != len(styles):
        raise argparse.ArgumentTypeError("--styles 必须提供不重复的风格席位，例如 A,B,C,D 或 A,B,C,D,E,F,G,H")
    invalid = [style for style in styles if style not in QUICK_STYLES]
    if invalid:
        raise argparse.ArgumentTypeError(f"--styles 包含无效席位：{','.join(invalid)}")
    return styles


def infer_styles(project_dir: Path, pages: list[str], source_state: dict | None) -> list[str]:
    if source_state is not None:
        state_styles = source_state.get("styles")
        if isinstance(state_styles, dict):
            result = [style for style in QUICK_STYLES if style in state_styles]
            if result:
                return result
    origin_dir = project_dir / "origin_image"
    if len(pages) == 1 and (
        any(
            path.suffix.lower() in IMAGE_SUFFIXES
            for path in origin_dir.glob("style_E_page_*.*")
        )
        or (origin_dir / "style_E").exists()
    ):
        return list(QUICK_STYLES)
    return list(FULL_STYLES)


def tone_label_for_styles(styles: list[str], source_state: dict | None) -> str:
    if source_state is None:
        return "深色" if styles and styles[0] in FULL_STYLES else "浅色"
    tones = {
        ((source_state.get("styles") or {}).get(style) or {}).get("tone")
        for style in styles
    }
    tones.discard(None)
    if tones == {"dark"}:
        return "深色"
    if tones == {"light"}:
        return "浅色"
    return "混合"


def find_page(project_dir: Path, style: str, page_id: str, source_state: dict | None = None) -> Path:
    if source_state is not None:
        try:
            raw_path = source_state["styles"][style]["pages"][page_id]["selected_source"]
        except (KeyError, TypeError) as exc:
            raise FileNotFoundError(f"运行状态缺少 style_{style}/page_{page_id} 的 selected_source") from exc
        if not isinstance(raw_path, str) or not raw_path.strip():
            raise FileNotFoundError(f"运行状态中的 style_{style}/page_{page_id} 尚无 selected_source")
        path = Path(raw_path).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"原始图片不存在：{path}")
        return path
    origin_dir = project_dir / "origin_image"
    matches = [
        path
        for path in origin_dir.glob(f"style_{style}_page_{page_id}.*")
        if path.suffix.lower() in IMAGE_SUFFIXES
    ]
    if not matches:
        legacy_folder = origin_dir / f"style_{style}"
        matches = [
            path
            for path in legacy_folder.glob(f"page_{page_id}.*")
            if path.suffix.lower() in IMAGE_SUFFIXES
        ]
    if len(matches) != 1:
        raise FileNotFoundError(
            f"需要且只能存在一张 style_{style}_page_{page_id} 图片，实际找到 {len(matches)} 张"
        )
    return matches[0]


def load_and_validate(path: Path, ratio_tolerance: float) -> Image.Image:
    with Image.open(path) as source:
        image = source.convert("RGB")
    width, height = image.size
    if width <= 0 or height <= 0:
        raise ValueError(f"无效图片尺寸：{path}")
    ratio = width / height
    if abs(ratio - TARGET_RATIO) > ratio_tolerance:
        raise ValueError(
            f"图片不是横向 16:9：{path}，实际尺寸 {width}x{height}，比例 {ratio:.4f}"
        )
    return image


def choose_font(size: int) -> ImageFont.ImageFont:
    candidates = (
        Path("C:/Windows/Fonts/msyh.ttc"),
        Path("C:/Windows/Fonts/arial.ttf"),
    )
    for candidate in candidates:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size=size)
    return ImageFont.load_default()


def draw_invalid_placeholder(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    width: int,
    height: int,
    style: str,
    page_id: str,
    reason: str,
) -> None:
    draw.rectangle((x, y, x + width, y + height), fill="#E4E4E4", outline="#B42318", width=4)
    title_font = choose_font(max(20, width // 28))
    detail_font = choose_font(max(16, width // 40))
    draw.text((x + 24, y + 24), f"风格 {style}｜第 {page_id} 页", fill="#7A271A", font=title_font)
    draw.text((x + 24, y + 80), "缺失或无效，等待定向修复", fill="#202020", font=detail_font)
    short_reason = reason if len(reason) <= 80 else reason[:77] + "..."
    draw.text((x + 24, y + 120), short_reason, fill="#555555", font=detail_font)


def build_matrix(
    project_dir: Path,
    styles: list[str],
    pages: list[str],
    output: Path,
    cell_width: int,
    header_height: int,
    row_label_width: int,
    gap: int,
    ratio_tolerance: float,
    source_state: dict | None = None,
    allow_invalid: bool = False,
) -> list[str]:
    cell_height = round(cell_width / TARGET_RATIO)
    quick_four_row = len(styles) == 8 and len(pages) == 1
    if quick_four_row:
        column_count = 2
        row_specs = tuple(
            (
                tone_label_for_styles(styles[start : start + 2], source_state),
                pages[0],
                styles[start : start + 2],
            )
            for start in range(0, 8, 2)
        )
        canvas_width = row_label_width + column_count * cell_width + (column_count + 1) * gap
        canvas_height = len(row_specs) * (header_height + cell_height + gap) + gap
        canvas = Image.new("RGB", (canvas_width, canvas_height), "#F2F2F2")
        draw = ImageDraw.Draw(canvas)
        header_font = choose_font(max(20, header_height // 3))
        row_font = choose_font(max(18, row_label_width // 5))
        invalid_cells: list[str] = []

        for row, (tone_label, page_id, row_styles) in enumerate(row_specs):
            block_top = gap + row * (header_height + cell_height + gap)
            image_y = block_top + header_height
            row_label = f"{tone_label}\n第 {page_id} 页"
            box = draw.multiline_textbbox((0, 0), row_label, font=row_font, spacing=10, align="center")
            text_width = box[2] - box[0]
            text_height = box[3] - box[1]
            draw.multiline_text(
                ((row_label_width - text_width) / 2, image_y + (cell_height - text_height) / 2),
                row_label,
                fill="#303030",
                font=row_font,
                spacing=10,
                align="center",
            )

            for column, style in enumerate(row_styles):
                x = row_label_width + gap + column * (cell_width + gap)
                label = f"风格 {style}"
                box = draw.textbbox((0, 0), label, font=header_font)
                text_width = box[2] - box[0]
                text_height = box[3] - box[1]
                draw.text(
                    (x + (cell_width - text_width) / 2, block_top + (header_height - text_height) / 2),
                    label,
                    fill="#202020",
                    font=header_font,
                )
                try:
                    path = find_page(project_dir, style, page_id, source_state)
                    image = load_and_validate(path, ratio_tolerance)
                except (FileNotFoundError, ValueError, OSError) as exc:
                    if not allow_invalid:
                        raise
                    message = f"style_{style}/page_{page_id}: {exc}"
                    invalid_cells.append(message)
                    draw_invalid_placeholder(
                        draw, x, image_y, cell_width, cell_height, style, page_id, str(exc)
                    )
                    continue
                resized = image.resize((cell_width, cell_height), Image.Resampling.LANCZOS)
                canvas.paste(resized, (x, image_y))

        output.parent.mkdir(parents=True, exist_ok=True)
        canvas.save(output, format="PNG", optimize=True)
        print(f"已生成：{output}")
        print(f"尺寸：{canvas.width}x{canvas.height}")
        if invalid_cells:
            print(f"警告：总览包含 {len(invalid_cells)} 个待修复占位单元格。", file=sys.stderr)
            for item in invalid_cells:
                print(f"- {item}", file=sys.stderr)
        return invalid_cells

    canvas_width = row_label_width + len(styles) * cell_width + (len(styles) + 1) * gap
    canvas_height = header_height + len(pages) * cell_height + (len(pages) + 1) * gap
    canvas = Image.new("RGB", (canvas_width, canvas_height), "#F2F2F2")
    draw = ImageDraw.Draw(canvas)
    header_font = choose_font(max(20, header_height // 3))
    row_font = choose_font(max(18, row_label_width // 5))
    invalid_cells: list[str] = []

    for column, style in enumerate(styles):
        x = row_label_width + gap + column * (cell_width + gap)
        label = f"风格 {style}"
        box = draw.textbbox((0, 0), label, font=header_font)
        text_width = box[2] - box[0]
        text_height = box[3] - box[1]
        draw.text(
            (x + (cell_width - text_width) / 2, (header_height - text_height) / 2),
            label,
            fill="#202020",
            font=header_font,
        )

    for row, page_id in enumerate(pages):
        y = header_height + gap + row * (cell_height + gap)
        row_label = f"第 {page_id} 页"
        box = draw.textbbox((0, 0), row_label, font=row_font)
        text_width = box[2] - box[0]
        text_height = box[3] - box[1]
        draw.text(
            ((row_label_width - text_width) / 2, y + (cell_height - text_height) / 2),
            row_label,
            fill="#303030",
            font=row_font,
        )

        for column, style in enumerate(styles):
            x = row_label_width + gap + column * (cell_width + gap)
            try:
                path = find_page(project_dir, style, page_id, source_state)
                image = load_and_validate(path, ratio_tolerance)
            except (FileNotFoundError, ValueError, OSError) as exc:
                if not allow_invalid:
                    raise
                message = f"style_{style}/page_{page_id}: {exc}"
                invalid_cells.append(message)
                draw_invalid_placeholder(draw, x, y, cell_width, cell_height, style, page_id, str(exc))
                continue
            resized = image.resize((cell_width, cell_height), Image.Resampling.LANCZOS)
            canvas.paste(resized, (x, y))

    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output, format="PNG", optimize=True)
    print(f"已生成：{output}")
    print(f"尺寸：{canvas.width}x{canvas.height}")
    if invalid_cells:
        print(f"警告：总览包含 {len(invalid_cells)} 个待修复占位单元格。", file=sys.stderr)
        for item in invalid_cells:
            print(f"- {item}", file=sys.stderr)
    return invalid_cells


def main() -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-dir", type=Path, required=True, help="包含 origin_image 的项目目录")
    parser.add_argument("--pages", type=parse_pages, required=True, help="一个或三个不同页面标识，逗号分隔")
    parser.add_argument("--styles", type=parse_styles, help="可选：显式指定风格列；默认从状态或目录推断")
    parser.add_argument("--output", type=Path, help="输出路径，默认生成 overview/ABCDEFGH_2x4.png 或 ABCD_4x3.png")
    parser.add_argument("--source-state", type=Path, help="可选：从运行状态中的 selected_source 读取原始图片，用于首轮临时总览")
    parser.add_argument("--cell-width", type=int, default=1280, help="每个页面在总览中的宽度")
    parser.add_argument("--header-height", type=int, default=120, help="总览顶部风格标签高度")
    parser.add_argument("--row-label-width", type=int, default=180, help="总览左侧页码标签宽度")
    parser.add_argument("--gap", type=int, default=24, help="页面之间的间距")
    parser.add_argument("--ratio-tolerance", type=float, default=0.02, help="16:9 比例允许误差")
    parser.add_argument(
        "--allow-invalid",
        action="store_true",
        help="临时质检模式：缺失或无效图片用占位单元格显示；正式总览不要使用",
    )
    args = parser.parse_args()

    project_dir = args.project_dir.resolve()
    source_state = None
    try:
        if args.source_state:
            with args.source_state.resolve().open("r", encoding="utf-8-sig") as handle:
                source_state = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    styles = args.styles or infer_styles(project_dir, args.pages, source_state)
    if len(args.pages) == 3 and styles != list(FULL_STYLES):
        parser.error("三页完整总览固定使用 A,B,C,D 四列")
    if len(args.pages) == 1 and len(styles) not in {4, 8}:
        parser.error("单页总览必须使用四个或八个风格席位")
    prefix = "".join(styles)
    default_name = (
        f"{prefix}_2x4.png"
        if len(styles) == 8 and len(args.pages) == 1
        else f"{prefix}_{len(styles)}x{len(args.pages)}.png"
    )
    output = (args.output or project_dir / "overview" / default_name).resolve()
    if args.cell_width < 320 or args.header_height < 40 or args.row_label_width < 80 or args.gap < 0:
        parser.error("画布参数过小或无效")
    if not 0 <= args.ratio_tolerance <= 0.2:
        parser.error("--ratio-tolerance 必须在 0 到 0.2 之间")
    if output.suffix.lower() != ".png":
        parser.error("--output 必须使用 .png 扩展名")

    try:
        build_matrix(
            project_dir=project_dir,
            styles=styles,
            pages=args.pages,
            output=output,
            cell_width=args.cell_width,
            header_height=args.header_height,
            row_label_width=args.row_label_width,
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
