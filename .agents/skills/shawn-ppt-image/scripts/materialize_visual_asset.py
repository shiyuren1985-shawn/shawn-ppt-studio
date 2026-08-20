#!/usr/bin/env python3
"""Materialize one explicitly located visual source into an ImageGen raster.

The source may be an existing raster, a PDF page, an Office document page or
slide, a local HTML page, a web URL, or a common image format that macOS can
convert.  The output and its provenance receipt are created before a formal
generation job freezes its attachment list.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import Any
from urllib.parse import urlparse


MATERIALIZATION_VERSION = 1
IMAGEGEN_RASTER_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
CONVERTIBLE_IMAGE_SUFFIXES = {
    ".svg", ".bmp", ".gif", ".heic", ".heif", ".tif", ".tiff"
}
PRESENTATION_SUFFIXES = {".ppt", ".pptx", ".pptm", ".odp"}
DOCUMENT_SUFFIXES = {".doc", ".docx", ".docm", ".odt", ".rtf"}
HTML_SUFFIXES = {".html", ".htm"}
WEB_SCHEMES = {"http", "https", "file"}
DEFAULT_VIEWPORT = {"width": 1600, "height": 900}


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    handle, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def require_positive_integer(value: Any, label: str) -> int:
    if isinstance(value, bool):
        raise SystemExit(f"{label} 必须是正整数")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise SystemExit(f"{label} 必须是正整数") from exc
    if result < 1:
        raise SystemExit(f"{label} 必须是正整数")
    return result


def normalize_viewport(value: Any) -> dict[str, int]:
    if value is None:
        return dict(DEFAULT_VIEWPORT)
    if not isinstance(value, dict):
        raise SystemExit("网页 locator.viewport 必须是包含 width/height 的对象")
    width = require_positive_integer(value.get("width"), "网页 viewport.width")
    height = require_positive_integer(value.get("height"), "网页 viewport.height")
    if not 320 <= width <= 7680 or not 240 <= height <= 4320:
        raise SystemExit("网页 viewport 超出 320×240 到 7680×4320 的支持范围")
    return {"width": width, "height": height}


def resolve_tool(
    *, env_name: str, commands: tuple[str, ...], candidates: tuple[Path, ...]
) -> Path:
    values: list[Path] = []
    configured = os.environ.get(env_name)
    if configured:
        values.append(Path(configured).expanduser())
    for command in commands:
        discovered = shutil.which(command)
        if discovered:
            values.append(Path(discovered))
    values.extend(candidates)
    for candidate in values:
        resolved = candidate.expanduser().resolve()
        if resolved.is_file() and os.access(resolved, os.X_OK):
            return resolved
    raise SystemExit(
        f"缺少视觉资产转换器：{env_name}；请安装对应工具或设置该环境变量"
    )


def runtime_tool(name: str) -> Path:
    return (
        Path.home()
        / ".cache/codex-runtimes/codex-primary-runtime/dependencies/bin/override"
        / name
    )


def resolve_pdftoppm() -> Path:
    return resolve_tool(
        env_name="SHAWN_PPT_PDFTOPPM",
        commands=("pdftoppm",),
        candidates=(runtime_tool("pdftoppm"),),
    )


def resolve_office() -> Path:
    return resolve_tool(
        env_name="SHAWN_PPT_OFFICE_RENDERER",
        commands=("soffice", "libreoffice"),
        candidates=(
            runtime_tool("soffice"),
            Path("/Applications/LibreOffice.app/Contents/MacOS/soffice"),
        ),
    )


def resolve_chrome() -> Path:
    return resolve_tool(
        env_name="SHAWN_PPT_CHROME",
        commands=("google-chrome", "chromium", "chromium-browser"),
        candidates=(
            Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
            Path("/Applications/Chromium.app/Contents/MacOS/Chromium"),
        ),
    )


def resolve_sips() -> Path:
    return resolve_tool(
        env_name="SHAWN_PPT_IMAGE_CONVERTER",
        commands=("sips",),
        candidates=(Path("/usr/bin/sips"),),
    )


def run_checked(
    command: list[str],
    label: str,
    timeout: int = 90,
    env: dict[str, str] | None = None,
) -> None:
    try:
        completed = subprocess.run(
            command,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        raise SystemExit(f"{label}超时") from exc
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise SystemExit(f"{label}失败：{detail or 'converter returned an error'}")


def verify_png(path: Path, label: str) -> None:
    if not path.is_file() or path.stat().st_size < 8:
        raise SystemExit(f"{label}未生成有效 PNG：{path}")
    if path.read_bytes()[:8] != b"\x89PNG\r\n\x1a\n":
        raise SystemExit(f"{label}输出不是 PNG：{path}")


def render_pdf_page(source: Path, page_number: int, output: Path) -> str:
    with tempfile.TemporaryDirectory(prefix="visual_pdf_", dir=output.parent) as temp:
        prefix = Path(temp) / "page"
        run_checked(
            [
                str(resolve_pdftoppm()),
                "-f", str(page_number),
                "-l", str(page_number),
                "-singlefile",
                "-r", "144",
                "-png",
                str(source),
                str(prefix),
            ],
            f"渲染 PDF 第 {page_number} 页",
        )
        rendered = prefix.with_suffix(".png")
        verify_png(rendered, "PDF 页渲染")
        os.replace(rendered, output)
    return "pdftoppm"


def render_office_page(source: Path, page_number: int, output: Path) -> str:
    with tempfile.TemporaryDirectory(prefix="visual_office_", dir=output.parent) as temp:
        temp_dir = Path(temp)
        profile = temp_dir / "office-profile"
        run_checked(
            [
                str(resolve_office()),
                f"-env:UserInstallation={profile.as_uri()}",
                "--headless",
                "--convert-to", "pdf",
                "--outdir", str(temp_dir),
                str(source),
            ],
            "将 Office 来源转换为 PDF",
            timeout=120,
        )
        pdf_candidates = sorted(temp_dir.glob("*.pdf"))
        if len(pdf_candidates) != 1:
            raise SystemExit("Office 转换没有生成唯一 PDF")
        render_pdf_page(pdf_candidates[0], page_number, output)
    return "soffice+pdftoppm"


def render_convertible_image(source: Path, output: Path) -> str:
    with tempfile.TemporaryDirectory(prefix="visual_image_", dir=output.parent) as temp:
        rendered = Path(temp) / "image.png"
        run_checked(
            [str(resolve_sips()), "-s", "format", "png", str(source), "--out", str(rendered)],
            "转换图片来源",
        )
        verify_png(rendered, "图片转换")
        os.replace(rendered, output)
    return "sips"


def render_web_page(
    source_url: str, viewport: dict[str, int], wait_ms: int, output: Path
) -> str:
    node = resolve_tool(
        env_name="SHAWN_PPT_NODE",
        commands=("node",),
        candidates=(
            Path.home()
            / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node",
        ),
    )
    chrome = resolve_chrome()
    runtime_modules = (
        Path.home()
        / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules"
    )
    node_modules = os.environ.get("SHAWN_PPT_NODE_MODULES") or str(runtime_modules)
    capture_script = Path(__file__).resolve().with_name("capture_web_visual.js")
    if not capture_script.is_file():
        raise SystemExit(f"缺少网页视觉截图脚本：{capture_script}")
    with tempfile.TemporaryDirectory(prefix="visual_web_", dir=output.parent) as temp:
        temp_dir = Path(temp)
        rendered = temp_dir / "web.png"
        child_env = dict(os.environ)
        child_env["NODE_PATH"] = node_modules
        child_env["SHAWN_PPT_CHROME"] = str(chrome)
        run_checked(
            [
                str(node),
                str(capture_script),
                source_url,
                str(rendered),
                str(viewport["width"]),
                str(viewport["height"]),
                str(wait_ms),
            ],
            "截取网页视觉来源",
            timeout=max(45, wait_ms // 1000 + 30),
            env=child_env,
        )
        verify_png(rendered, "网页截图")
        os.replace(rendered, output)
    return "playwright+chrome"


def safe_stem(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._-")
    return (slug or "visual_source")[:80]


def parse_spec_json(value: str) -> dict[str, Any]:
    try:
        spec = json.loads(value)
    except json.JSONDecodeError as exc:
        raise SystemExit("视觉资产 spec 必须是合法 JSON 对象") from exc
    if not isinstance(spec, dict):
        raise SystemExit("视觉资产 spec 根节点必须是对象")
    return spec


def normalize_spec(spec: dict[str, Any]) -> dict[str, Any]:
    source = spec.get("source")
    role = spec.get("role")
    if not isinstance(source, str) or not source.strip():
        raise SystemExit("视觉资产 spec.source 必须是非空路径或 URL")
    if not isinstance(role, str) or not role.strip():
        raise SystemExit("视觉资产 spec.role 必须是非空字符串")
    locator = spec.get("locator") or {}
    if not isinstance(locator, dict):
        raise SystemExit("视觉资产 spec.locator 必须是对象")
    return {
        "source": source.strip(),
        "role": role.strip(),
        "locator": locator,
    }


def materialize_visual_asset(
    spec_value: dict[str, Any], output_dir_value: str | Path
) -> dict[str, Any]:
    spec = normalize_spec(spec_value)
    output_dir = Path(output_dir_value).expanduser()
    if not output_dir.is_absolute():
        raise SystemExit("视觉资产输出目录必须是绝对路径")
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    source_text = spec["source"]
    parsed = urlparse(source_text)
    is_web = parsed.scheme.lower() in WEB_SCHEMES
    source_path: Path | None = None
    source_sha: str | None = None
    if is_web and parsed.scheme.lower() == "file":
        source_path = Path(parsed.path).expanduser().resolve()
        if not source_path.is_file():
            raise SystemExit(f"网页视觉来源不存在：{source_path}")
        source_sha = file_sha256(source_path)
    elif not is_web:
        source_path = Path(source_text).expanduser()
        if not source_path.is_absolute():
            raise SystemExit(f"视觉资产本地来源必须是绝对路径：{source_text}")
        source_path = source_path.resolve()
        if not source_path.is_file():
            raise SystemExit(f"视觉资产来源不存在：{source_path}")
        source_sha = file_sha256(source_path)

    suffix = source_path.suffix.lower() if source_path is not None else ""
    locator: dict[str, Any] = {}
    renderer: str
    source_kind: str
    output_path: Path

    if source_path is not None and suffix in IMAGEGEN_RASTER_SUFFIXES:
        if spec["locator"]:
            raise SystemExit("现成光栅图片不接受 page/slide/viewport locator")
        source_kind = "raster"
        renderer = "passthrough"
        output_path = source_path
    else:
        if source_path is not None and suffix == ".pdf":
            page = require_positive_integer(spec["locator"].get("page"), "PDF locator.page")
            locator = {"page": page}
            source_kind = "pdf_page"
        elif source_path is not None and suffix in PRESENTATION_SUFFIXES:
            slide = require_positive_integer(
                spec["locator"].get("slide", spec["locator"].get("page")),
                "演示文稿 locator.slide",
            )
            locator = {"slide": slide}
            source_kind = "presentation_slide"
        elif source_path is not None and suffix in DOCUMENT_SUFFIXES:
            page = require_positive_integer(spec["locator"].get("page"), "文档 locator.page")
            locator = {"page": page}
            source_kind = "document_page"
        elif source_path is not None and suffix in CONVERTIBLE_IMAGE_SUFFIXES:
            if spec["locator"]:
                raise SystemExit("可转换图片不接受 page/slide/viewport locator")
            source_kind = "converted_image"
        elif is_web or (source_path is not None and suffix in HTML_SUFFIXES):
            viewport = normalize_viewport(spec["locator"].get("viewport"))
            wait_ms = int(spec["locator"].get("wait_ms", 1500))
            if not 0 <= wait_ms <= 30000:
                raise SystemExit("网页 locator.wait_ms 必须介于 0 和 30000")
            locator = {"viewport": viewport, "wait_ms": wait_ms}
            source_kind = "web_viewport"
        else:
            suffix_label = suffix or parsed.scheme or "unknown"
            raise SystemExit(
                f"尚不支持的视觉资产来源类型：{suffix_label}；"
                "请增加 materializer 适配器，不要把原文件直接传给 ImageGen"
            )

        fingerprint_payload = {
            "version": MATERIALIZATION_VERSION,
            "source": str(source_path) if source_path is not None else source_text,
            "source_sha256": source_sha,
            "source_kind": source_kind,
            "locator": locator,
        }
        fingerprint = hashlib.sha256(
            json.dumps(
                fingerprint_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        if source_path is not None:
            stem = safe_stem(source_path.stem)
        else:
            stem = safe_stem(parsed.netloc + parsed.path)
        output_path = output_dir / f"{stem}_{fingerprint[:16]}.png"
        receipt_path = output_dir / f"{stem}_{fingerprint[:16]}.materialization.json"
        if receipt_path.is_file():
            try:
                previous = json.loads(receipt_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise SystemExit(f"视觉资产转换回执损坏：{receipt_path}") from exc
            if (
                previous.get("spec_sha256") == fingerprint
                and output_path.is_file()
                and previous.get("output_sha256") == file_sha256(output_path)
            ):
                previous["receipt_path"] = str(receipt_path)
                previous["role"] = spec["role"]
                return previous
            raise SystemExit(f"视觉资产转换缓存与来源不一致：{receipt_path}")

        if output_path.is_file():
            verify_png(output_path, "既有视觉资产转换缓存")
        elif source_kind == "pdf_page":
            renderer = render_pdf_page(source_path, locator["page"], output_path)
        elif source_kind in {"presentation_slide", "document_page"}:
            page_number = locator.get("slide", locator.get("page"))
            renderer = render_office_page(source_path, page_number, output_path)
        elif source_kind == "converted_image":
            renderer = render_convertible_image(source_path, output_path)
        else:
            web_source = (
                source_path.as_uri()
                if source_path is not None and not is_web
                else source_text
            )
            renderer = render_web_page(
                web_source,
                locator["viewport"],
                locator["wait_ms"],
                output_path,
            )
        if output_path.is_file() and 'renderer' not in locals():
            renderer = "cached-output"
        verify_png(output_path, "视觉资产转换")

    canonical_spec = {
        "source": str(source_path) if source_path is not None else source_text,
        "role": spec["role"],
        "locator": locator,
    }
    spec_fingerprint = hashlib.sha256(
        json.dumps(
            {
                "version": MATERIALIZATION_VERSION,
                "source": canonical_spec["source"],
                "source_sha256": source_sha,
                "source_kind": source_kind,
                "locator": locator,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    receipt_path = output_dir / (
        f"{safe_stem(source_path.stem if source_path is not None else parsed.netloc + parsed.path)}_"
        f"{spec_fingerprint[:16]}.materialization.json"
    )
    receipt = {
        "materialized_visual_asset_version": MATERIALIZATION_VERSION,
        "spec_sha256": spec_fingerprint,
        "source_kind": source_kind,
        "source": canonical_spec["source"],
        "source_sha256": source_sha,
        "locator": locator,
        "renderer": renderer,
        "output_path": str(output_path),
        "output_sha256": file_sha256(output_path),
        "source_file": str(source_path) if source_path is not None else None,
    }
    if receipt_path.exists():
        previous = json.loads(receipt_path.read_text(encoding="utf-8"))
        if previous != receipt:
            raise SystemExit(f"拒绝覆盖不同的视觉资产转换回执：{receipt_path}")
    else:
        atomic_write_json(receipt_path, receipt)
    receipt["receipt_path"] = str(receipt_path)
    receipt["role"] = spec["role"]
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec-json", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    result = materialize_visual_asset(
        parse_spec_json(args.spec_json), args.output_dir
    )
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
