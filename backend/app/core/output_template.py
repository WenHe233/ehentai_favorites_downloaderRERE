from __future__ import annotations

import os
import string
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Mapping, Optional


DEFAULT_DATETIME_FORMAT = "%Y-%m-%d %H-%M-%S"
ALLOWED_TEMPLATE_FIELDS = {
    "gid",
    "title",
    "jpn_title",
    "category",
    "uploader",
    "filecount",
    "quality",
    "parent_gid",
    "downloaded_at",
    "favorited_at",
    "fav",
}
DATETIME_TEMPLATE_FIELDS = {"downloaded_at", "favorited_at"}
WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}
ILLEGAL_TRANSLATIONS = str.maketrans(
    {
        "<": "＜",
        ">": "＞",
        ":": "：",
        '"': "＂",
        "/": "／",
        "\\": "＼",
        "|": "｜",
        "?": "？",
        "*": "＊",
    }
)


class OutputTemplateError(ValueError):
    pass


@dataclass
class OutputTemplateSettings:
    template: str
    conflict_strategy: str
    truncate_enabled: bool
    max_length: int
    timezone_mode: Optional[str]
    base_dir: Path


def get_default_filename_max_length() -> int:
    return 160 if os.name == "nt" else 220


def normalize_quality_preference(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if raw == "resample":
        raw = "native"
    if raw not in {"original", "native"}:
        return "original"
    return raw


def validate_output_settings(
    *,
    template: Any,
    conflict_strategy: Any,
    truncate_enabled: Any,
    max_length: Any,
) -> None:
    validate_output_template(str(template or "").strip())

    strategy = str(conflict_strategy or "").strip().lower()
    if strategy not in {"rename", "overwrite"}:
        raise OutputTemplateError("冲突策略只能是 rename 或 overwrite")

    if not isinstance(truncate_enabled, bool):
        raise OutputTemplateError("文件名截断开关必须是 true 或 false")

    if truncate_enabled:
        try:
            length = int(max_length)
        except (TypeError, ValueError) as exc:
            raise OutputTemplateError("文件名长度限制必须是整数") from exc
        if length < 16:
            raise OutputTemplateError("文件名长度限制不能小于 16")
        if length > 240:
            raise OutputTemplateError("文件名长度限制不能大于 240")


def validate_output_template(template: str) -> None:
    if not template or not template.strip():
        raise OutputTemplateError("输出路径模板不能为空")

    stripped = template.strip()
    if stripped.endswith(("/", "\\")):
        raise OutputTemplateError("输出路径模板必须包含文件名，不能只填写目录")

    try:
        chunks = list(string.Formatter().parse(stripped))
    except ValueError as exc:
        raise OutputTemplateError(f"输出路径模板格式错误: {exc}") from exc

    for literal_text, field_name, format_spec, conversion in chunks:
        if conversion:
            raise OutputTemplateError("输出路径模板不支持转换语法")

        for segment in _split_literal_segments(literal_text):
            if segment == "..":
                raise OutputTemplateError("输出路径模板不允许使用 .. 向上跳目录")

        if field_name is None:
            continue

        field_key = field_name.strip()
        if not field_key:
            raise OutputTemplateError("输出路径模板中存在空占位符")
        if field_key not in ALLOWED_TEMPLATE_FIELDS:
            allowed = ", ".join(sorted(ALLOWED_TEMPLATE_FIELDS))
            raise OutputTemplateError(f"不支持的占位符 {{{field_key}}}。可用字段: {allowed}")
        if format_spec and field_key not in DATETIME_TEMPLATE_FIELDS:
            raise OutputTemplateError(f"只有时间字段支持格式化: {{{field_key}:{format_spec}}}")


def build_output_path(
    *,
    settings: OutputTemplateSettings,
    context: Mapping[str, Any],
    partial: bool = False,
) -> Path:
    rendered = _render_template(settings.template, context, settings.timezone_mode)
    return _resolve_rendered_path(
        rendered,
        base_dir=settings.base_dir,
        truncate_enabled=settings.truncate_enabled,
        max_length=settings.max_length,
        conflict_strategy=settings.conflict_strategy,
        partial=partial,
    )


def resolve_output_targets(
    *,
    settings: OutputTemplateSettings,
    context: Mapping[str, Any],
) -> tuple[Path, Path]:
    rendered = _render_template(settings.template, context, settings.timezone_mode)
    final_candidate = _resolve_rendered_path(
        rendered,
        base_dir=settings.base_dir,
        truncate_enabled=settings.truncate_enabled,
        max_length=settings.max_length,
        conflict_strategy="overwrite",
        partial=False,
    )
    partial_candidate = with_partial_suffix(final_candidate)

    if settings.conflict_strategy == "rename":
        final_candidate, partial_candidate = _ensure_unique_pair(final_candidate, partial_candidate)

    return final_candidate, partial_candidate


def build_output_context(
    *,
    gid: Any,
    title: Any,
    jpn_title: Any,
    category: Any,
    uploader: Any,
    filecount: Any,
    quality: Any,
    parent_gid: Any,
    downloaded_at: Optional[datetime],
    favorited_at: Optional[datetime],
    fav: Any,
) -> dict[str, Any]:
    normalized_title = _normalize_string(title)
    normalized_jpn_title = _normalize_string(jpn_title) or normalized_title
    return {
        "gid": gid,
        "title": normalized_title,
        "jpn_title": normalized_jpn_title,
        "category": _normalize_string(category),
        "uploader": _normalize_string(uploader),
        "filecount": filecount,
        "quality": _normalize_string(quality),
        "parent_gid": _normalize_string(parent_gid),
        "downloaded_at": downloaded_at,
        "favorited_at": favorited_at,
        "fav": fav,
    }


def with_partial_suffix(path: Path) -> Path:
    suffix = path.suffix
    name = path.name
    if suffix:
        stem = name[: -len(suffix)]
        partial_name = f"{stem}.partial{suffix}"
    else:
        partial_name = f"{name}.partial"
    return path.with_name(partial_name)


def with_temp_suffix(path: Path, marker: str = ".tmpdownload") -> Path:
    suffix = path.suffix
    name = path.name
    if suffix:
        stem = name[: -len(suffix)]
        temp_name = f"{stem}{marker}{suffix}"
    else:
        temp_name = f"{name}{marker}"
    return path.with_name(temp_name)


def ensure_unique_path(path: Path) -> Path:
    if not path.exists():
        return path

    suffix = path.suffix
    name = path.name
    stem = name[: -len(suffix)] if suffix else name
    counter = 1
    while True:
        candidate_name = f"{stem}_{counter}{suffix}"
        candidate = path.with_name(candidate_name)
        if not candidate.exists():
            return candidate
        counter += 1


def _ensure_unique_pair(final_path: Path, partial_path: Path) -> tuple[Path, Path]:
    if not final_path.exists() and not partial_path.exists():
        return final_path, partial_path

    suffix = final_path.suffix
    name = final_path.name
    stem = name[: -len(suffix)] if suffix else name
    counter = 1
    while True:
        candidate_name = f"{stem}_{counter}{suffix}"
        candidate_final = final_path.with_name(candidate_name)
        candidate_partial = with_partial_suffix(candidate_final)
        if not candidate_final.exists() and not candidate_partial.exists():
            return candidate_final, candidate_partial
        counter += 1


def resolve_relative_output_base(base_dir: Path, template: str) -> Path:
    candidate = Path(template)
    if candidate.is_absolute():
        return candidate
    return base_dir / candidate


def _render_template(template: str, context: Mapping[str, Any], timezone_mode: Optional[str]) -> str:
    parts: list[str] = []
    try:
        chunks = string.Formatter().parse(template)
    except ValueError as exc:
        raise OutputTemplateError(f"输出路径模板格式错误: {exc}") from exc

    for literal_text, field_name, format_spec, conversion in chunks:
        if conversion:
            raise OutputTemplateError("输出路径模板不支持转换语法")

        parts.append(literal_text)
        if field_name is None:
            continue

        if field_name not in ALLOWED_TEMPLATE_FIELDS:
            raise OutputTemplateError(f"不支持的占位符: {field_name}")
        value = context.get(field_name)
        parts.append(_format_field_value(field_name, value, format_spec, timezone_mode))

    return "".join(parts).strip()


def _format_field_value(
    field_name: str,
    value: Any,
    format_spec: str,
    timezone_mode: Optional[str],
) -> str:
    if field_name in DATETIME_TEMPLATE_FIELDS:
        if value is None:
            return ""
        if not isinstance(value, datetime):
            raise OutputTemplateError(f"{field_name} 必须是时间类型")
        dt = _convert_datetime(value, timezone_mode)
        return _sanitize_placeholder_value(dt.strftime(format_spec or DEFAULT_DATETIME_FORMAT))

    if value is None:
        return ""
    if field_name == "filecount":
        return _sanitize_placeholder_value(str(int(value)))
    return _sanitize_placeholder_value(str(value))


def _convert_datetime(value: datetime, timezone_mode: Optional[str]) -> datetime:
    if timezone_mode == "site":
        return value

    if value.tzinfo is None:
        offset_seconds = -time.timezone
        return value + timedelta(seconds=offset_seconds)

    return value.astimezone()


def _resolve_rendered_path(
    rendered: str,
    *,
    base_dir: Path,
    truncate_enabled: bool,
    max_length: int,
    conflict_strategy: str,
    partial: bool,
) -> Path:
    if not rendered:
        raise OutputTemplateError("输出路径模板渲染结果为空")

    candidate = Path(rendered)
    anchor = candidate.anchor
    normalized_rendered = rendered.replace("\\", "/")
    raw_parts = normalized_rendered.split("/")
    sanitized_parts: list[str] = []

    if anchor:
        anchor_text = anchor.replace("\\", "/")
        normalized_rendered = normalized_rendered[len(anchor_text):]
        raw_parts = normalized_rendered.split("/")

    for index, part in enumerate(raw_parts):
        if not part or part == ".":
            continue
        if part == "..":
            raise OutputTemplateError("输出路径模板不允许使用 .. 向上跳目录")
        sanitized_parts.append(_sanitize_path_segment(part))

    if not sanitized_parts:
        sanitized_parts.append("未知")

    root = Path(anchor) if anchor else base_dir
    resolved = root.joinpath(*sanitized_parts).absolute()
    # Reserve space for .partial, .tmpdownload and collision numbering.
    reserve = 32
    for segment in resolved.parent.parts[1:]:
        if _filesystem_length(segment) > 255:
            raise OutputTemplateError("输出目录名过长，请缩短目录或输出路径模板")
    component_budget = 255 - reserve
    if os.name == "nt":
        component_budget = min(component_budget, 259 - _filesystem_length(str(resolved.parent)) - 1 - reserve)
    if component_budget < 16:
        raise OutputTemplateError("输出目录路径过长，请选择更短的下载目录")
    resolved = resolved.with_name(_truncate_filename_if_needed(resolved.name, truncate_enabled, max_length, component_budget))
    if partial:
        resolved = with_partial_suffix(resolved)
    resolved.parent.mkdir(parents=True, exist_ok=True)

    if conflict_strategy == "rename":
        resolved = ensure_unique_path(resolved)

    return resolved


def _filesystem_length(value: str) -> int:
    return len(value.encode("utf-16-le")) // 2 if os.name == "nt" else len(value.encode("utf-8"))


def _truncate_filename_if_needed(name: str, truncate_enabled: bool, max_length: int, filesystem_budget: int = 223) -> str:
    if not name:
        name = "未知"

    name = _sanitize_path_segment(name, is_filename=True)
    suffix = Path(name).suffix
    # A dot in a gallery title is not the beginning of a compound extension.
    if len(suffix) > 16:
        suffix = ""
    stem = name[: -len(suffix)] if suffix else name
    if not truncate_enabled:
        if _filesystem_length(name) > filesystem_budget:
            raise OutputTemplateError("文件名过长，请启用文件名截断或缩短输出路径模板后重试")
        return name
    remaining = max(1, max_length - len(suffix))
    stem = stem[:remaining]
    while stem and _filesystem_length(stem + suffix) > filesystem_budget:
        stem = stem[:-1]
    if not stem:
        raise OutputTemplateError("输出文件名没有足够空间，请缩短输出目录")
    result = _sanitize_path_segment(stem + suffix, is_filename=True)
    # Sanitizing a reserved Windows name may insert one extra character.
    if len(result) > max_length or _filesystem_length(result) > filesystem_budget:
        return _truncate_filename_if_needed("_" + stem[:-2] + suffix, True, max_length, filesystem_budget)
    return result


def _sanitize_placeholder_value(value: str) -> str:
    sanitized = value.translate(ILLEGAL_TRANSLATIONS)
    sanitized = "".join(_normalize_char(ch) for ch in sanitized)
    sanitized = sanitized.replace("/", "／").replace("\\", "＼")
    return sanitized.strip()


def _sanitize_path_segment(segment: str, *, is_filename: bool = False) -> str:
    normalized = segment.translate(ILLEGAL_TRANSLATIONS)
    normalized = "".join(_normalize_char(ch) for ch in normalized).strip()
    normalized = normalized.rstrip(" .")
    normalized = normalized or "未知"

    if os.name == "nt":
        root_name = normalized.split(".")[0].upper()
        if root_name in WINDOWS_RESERVED_NAMES:
            normalized = f"_{normalized}"

    if is_filename and normalized in {".", ".."}:
        normalized = "未知"

    return normalized


def _normalize_char(ch: str) -> str:
    codepoint = ord(ch)
    if codepoint < 32:
        return "_"
    if ch in {'"', "/", "\\", "|", "?", "*", "<", ">", ":"}:
        return "_"
    return ch


def _split_literal_segments(text: str) -> list[str]:
    return [segment for segment in text.replace("\\", "/").split("/") if segment]


def _normalize_string(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()
