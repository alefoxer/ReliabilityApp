"""Shared helpers for LaTeX-first formula rendering across UI and exports."""

from __future__ import annotations

import base64
from dataclasses import asdict
from html import escape
import io
import re
import xml.etree.ElementTree as ET
from typing import Any

from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from PIL import Image

FORMULA_FONT_SIZE = 13
FORMULA_DPI = 160
FORMULA_LINE_GAP = 6
FORMULA_PADDING = 2
SVG_NS = "http://www.w3.org/2000/svg"

FORMULA_SECTION_STYLE = (
    "margin:12px 0 6px 0; color:#163f63; font-size:13px; "
    "font-weight:700; line-height:1.25;"
)
FORMULA_CARD_STYLE = (
    "margin:6px 0; padding:8px 10px; background:#ffffff; "
    "border:1px solid #d8e0ea; border-radius:8px;"
)
FORMULA_LABEL_STYLE = (
    "margin-bottom:4px; color:#1f2937; font-size:12px; "
    "font-weight:700; line-height:1.25; word-break:break-word;"
)
FORMULA_META_STYLE = (
    "margin-top:4px; color:#536274; font-size:11px; "
    "line-height:1.25; word-break:break-word;"
)


RESULT_METRIC_FORMULAS: dict[str, str] = {
    "P": "P(t) = вероятность безотказной работы системы за время t",
    "Kg": "Kг = T0 / (T0 + Tв)",
    "Kog": "Kог = Kг · P(t)",
    "T0": "T0 = средняя наработка до отказа",
    "Tv": "Tв = среднее время восстановления",
    "Tpr": "Tпр = среднее время простоя",
    "lambda": "λ = 1 / T0",
}

RESULT_METRIC_LATEX: dict[str, str] = {
    "P": r"P(t)",
    "Kg": r"K_{\text{г}} = \frac{T_0}{T_0 + T_{\text{в}}}",
    "Kog": r"K_{\text{ог}} = K_{\text{г}} \cdot P(t)",
    "T0": r"T_0",
    "Tv": r"T_{\text{в}}",
    "Tpr": r"T_{\text{пр}}",
    "lambda": r"\lambda = \frac{1}{T_0}",
}


def latex_formula_text(text: object) -> str:
    """Return a stable LaTeX representation for project formula strings."""
    result = str(text or "").strip()
    if not result:
        return ""
    replacements = {
        "Pсист": r"P_{\text{сист}}",
        "Pсер": r"P_{\text{сер}}",
        "Pпар": r"P_{\text{пар}}",
        "Pрез": r"P_{\text{рез}}",
        "Kг_сист": r"K_{\text{г,сист}}",
        "Kг": r"K_{\text{г}}",
        "Kог": r"K_{\text{ог}}",
        "Tв": r"T_{\text{в}}",
        "Tv": r"T_{\text{в}}",
        "t_v": r"t_{\text{в}}",
        "λ": r"\lambda",
        "О»": r"\lambda",
        "Σ": r"\sum",
        "∑": r"\sum",
        "∏": r"\prod",
        "Π": r"\prod",
        " · ": r" \cdot ",
        " В· ": r" \cdot ",
        " * ": r" \cdot ",
        "...": r"\ldots",
        "manual verification required": r"\text{требуется ручная проверка}",
    }
    for source, target in replacements.items():
        result = result.replace(source, target)
    result = re.sub(r"\bexp\(-lambda_([A-Za-zА-Яа-я0-9_]+) \* t\)", r"e^{-\\lambda_{\1} t}", result)
    result = re.sub(r"\b([BPR]\d+)\b", r"P_{\\text{\1}}", result)
    result = re.sub(r"\^([0-9]+)", r"^{\1}", result)
    return result


def latex_block(text: object) -> str:
    """Wrap a formula as display LaTeX unless it is already wrapped."""
    formula = latex_formula_text(text)
    if not formula:
        return ""
    if formula.startswith("\\[") or formula.startswith("$"):
        return formula
    return "\\[\n" + formula + "\n\\]"


def normalize_latex_for_mathtext(text: object) -> str:
    """Normalize project LaTeX so matplotlib mathtext can render it reliably."""
    result = str(text or "").strip()
    if not result:
        return ""
    result = result.replace("\\[", "").replace("\\]", "").strip()
    result = result.replace(r"\text{", r"\mathrm{")

    def _preserve_text_spacing(match: re.Match[str]) -> str:
        content = match.group(1)
        # Mathtext ignores regular spaces in \mathrm{...}, so make them explicit.
        content = re.sub(r"\s+", r"\\ ", content)
        return rf"\mathrm{{{content}}}"

    return re.sub(r"\\mathrm\{([^{}]*)\}", _preserve_text_spacing, result)


def is_renderable_latex_formula(text: object) -> bool:
    """Return True only for strings that are worth sending to mathtext."""
    value = str(text or "").strip()
    if not value:
        return False
    value = value.replace("\\[", "").replace("\\]", "").strip()
    if not value:
        return False
    explicit_tokens = (
        r"\frac",
        r"\cdot",
        r"\lambda",
        r"\sum",
        r"\prod",
        r"\text{",
        r"\mathrm{",
        "^{",
        "_{",
        "e^{-",
    )
    if any(token in value for token in explicit_tokens):
        return True
    if re.search(r"\b[PKT]\w*\s*=", value):
        return True
    if re.search(r"\b[PKT]_\w+", value):
        return True
    if re.search(r"\b[PKT]\([^)]*\)\s*=", value):
        return True
    return False


def split_latex_formula_for_display(text: object, *, max_line_length: int = 90) -> list[str]:
    """Split long display LaTeX at top-level operators without changing semantics."""
    formula = str(text or "").strip()
    if not formula:
        return []
    formula = formula.replace("\\[", "").replace("\\]", "").strip()
    if len(formula) <= max_line_length:
        return [formula]

    lhs, rhs = _split_top_level_assignment(formula)
    terms = _top_level_latex_terms(rhs)
    if len(terms) > 1:
        lines = _pack_latex_terms(lhs, terms, max_line_length=max_line_length)
        if len(lines) > 1:
            return lines

    complement_lines = _split_complement_product(lhs, rhs, max_line_length=max_line_length)
    if len(complement_lines) > 1:
        return complement_lines
    return [formula]


def readable_latex_lines_for_display(text: object, *, max_line_length: int = 90) -> list[str]:
    """Return readable non-image formula lines for Qt rich-text views."""
    latex_lines = split_latex_formula_for_display(text, max_line_length=max_line_length)
    readable_lines = [readable_formula_text(line) for line in latex_lines]
    return [line for line in readable_lines if line]


def _split_top_level_assignment(formula: str) -> tuple[str, str]:
    depth = 0
    for index, char in enumerate(formula):
        depth = _latex_depth_after_char(char, depth)
        if char == "=" and depth == 0:
            return formula[: index + 1].strip(), formula[index + 1 :].strip()
    return "", formula


def _top_level_latex_terms(text: str) -> list[tuple[str, str]]:
    terms: list[tuple[str, str]] = []
    depth = 0
    start = 0
    pending_operator = ""
    index = 0
    while index < len(text):
        if depth == 0:
            if text.startswith(r"\cdot", index):
                _append_latex_term(terms, pending_operator, text[start:index])
                pending_operator = r"\cdot"
                index += len(r"\cdot")
                start = index
                continue
            if text[index] in {"+", "-"} and _is_binary_latex_operator(text, index):
                _append_latex_term(terms, pending_operator, text[start:index])
                pending_operator = text[index]
                index += 1
                start = index
                continue
        depth = _latex_depth_after_char(text[index], depth)
        index += 1
    _append_latex_term(terms, pending_operator, text[start:])
    return terms


def _append_latex_term(terms: list[tuple[str, str]], operator: str, raw_term: str) -> None:
    term = raw_term.strip()
    if term:
        terms.append((operator, term))


def _pack_latex_terms(lhs: str, terms: list[tuple[str, str]], *, max_line_length: int) -> list[str]:
    lines: list[str] = []
    current = ""
    for index, (operator, term) in enumerate(terms):
        prefix = _latex_continuation_prefix(operator)
        piece = term if index == 0 else f"{prefix}{term}".strip()
        candidate = f"{current} {piece}".strip() if current else f"{lhs} {piece}".strip()
        if current and len(candidate) > max_line_length:
            lines.append(current)
            current = piece
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def _split_complement_product(lhs: str, rhs: str, *, max_line_length: int) -> list[str]:
    if not rhs.startswith("1 - "):
        return []
    factors = _top_level_parenthesized_latex_factors(rhs[4:].strip())
    if len(factors) < 2:
        return []
    first, *rest = factors
    lines = [f"{lhs} 1 - {first}".strip() if lhs else f"1 - {first}"]
    current = ""
    for factor in rest:
        candidate = f"{current}{factor}" if current else factor
        if current and len(candidate) > max_line_length:
            lines.append(current)
            current = factor
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def _top_level_parenthesized_latex_factors(text: str) -> list[str]:
    result: list[str] = []
    index = 0
    while index < len(text):
        while index < len(text) and text[index].isspace():
            index += 1
        if index >= len(text):
            break
        if text[index] != "(":
            return []
        start = index
        depth = 0
        while index < len(text):
            char = text[index]
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    index += 1
                    break
            index += 1
        while index < len(text) and text[index].isspace():
            index += 1
        if index < len(text) and text[index] == "^":
            index = _consume_latex_suffix(text, index)
        result.append(text[start:index].strip())
    return result


def _consume_latex_suffix(text: str, index: int) -> int:
    index += 1
    if index < len(text) and text[index] == "{":
        depth = 1
        index += 1
        while index < len(text) and depth > 0:
            if text[index] == "{":
                depth += 1
            elif text[index] == "}":
                depth -= 1
            index += 1
    else:
        index += 1
    return index


def _latex_continuation_prefix(operator: str) -> str:
    if operator == r"\cdot":
        return r"\cdot "
    if operator in {"+", "-"}:
        return f"{operator} "
    return ""


def _is_binary_latex_operator(text: str, index: int) -> bool:
    before = text[:index].rstrip()
    after = text[index + 1 :].lstrip()
    return bool(before and after and before[-1] not in "({[=_^+-")


def _latex_depth_after_char(char: str, depth: int) -> int:
    if char in "({[":
        return depth + 1
    if char in ")}]":
        return max(0, depth - 1)
    if char == "{":
        return depth + 1
    if char == "}":
        return max(0, depth - 1)
    return depth


def _render_latex_figure(text: object, *, font_size: int = FORMULA_FONT_SIZE, dpi: int = FORMULA_DPI) -> Figure | None:
    """Prepare a tightly-fitted matplotlib figure for a single LaTeX formula."""
    formula = normalize_latex_for_mathtext(text)
    if not formula:
        return None

    fig = Figure(figsize=(0.01, 0.01), dpi=dpi)
    canvas = FigureCanvasAgg(fig)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.axis("off")
    rendered = ax.text(0.01, 0.5, f"${formula}$", fontsize=font_size, va="center", ha="left")
    canvas.draw()

    bbox = rendered.get_window_extent(renderer=canvas.get_renderer()).expanded(1.05, 1.35)
    width_in = max(bbox.width / fig.dpi, 0.01)
    height_in = max(bbox.height / fig.dpi, 0.01)
    fig.set_size_inches(width_in, height_in)
    ax.set_position([0, 0, 1, 1])
    rendered.set_position((0.01, 0.5))
    canvas.draw()
    return fig


def render_latex_to_png_bytes(text: object, *, font_size: int = FORMULA_FONT_SIZE, dpi: int = FORMULA_DPI) -> bytes:
    """Render a single LaTeX formula to PNG bytes using matplotlib mathtext."""
    fig = _render_latex_figure(text, font_size=font_size, dpi=dpi)
    if fig is None:
        return b""

    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", dpi=dpi, transparent=True, bbox_inches="tight", pad_inches=0.02)
    return buffer.getvalue()


def render_latex_to_svg_bytes(text: object, *, font_size: int = FORMULA_FONT_SIZE, dpi: int = FORMULA_DPI) -> bytes:
    """Render a single LaTeX formula to SVG bytes using matplotlib mathtext."""
    fig = _render_latex_figure(text, font_size=font_size, dpi=dpi)
    if fig is None:
        return b""

    buffer = io.BytesIO()
    fig.savefig(buffer, format="svg", dpi=dpi, transparent=True, bbox_inches="tight", pad_inches=0.02)
    return buffer.getvalue()


def _image_size_attrs(mime_type: str, payload: bytes) -> str:
    try:
        if mime_type == "image/png":
            with Image.open(io.BytesIO(payload)) as image:
                width, height = image.size
            return f" width='{int(width)}' height='{int(height)}'"
        if mime_type == "image/svg+xml":
            width, height, _ = _svg_dimensions(payload)
            return f" width='{max(1, int(width))}' height='{max(1, int(height))}'"
    except Exception:
        return ""
    return ""


def _image_block_html(*, mime_type: str, payload: bytes, margin: str = "6px 0", align: str = "left") -> str:
    encoded = base64.b64encode(payload).decode("ascii")
    size_attrs = _image_size_attrs(mime_type, payload)
    return (
        f"<div class='formula-latex-image' style='margin:{margin}; width:100%; text-align:{align}; overflow-x:auto; overflow-y:hidden;'>"
        f"<img src='data:{mime_type};base64,{encoded}'{size_attrs} "
        "style='max-width:none; height:auto; vertical-align:middle;'/>"
        "</div>"
    )


def latex_svg_html(text: object, *, font_size: int = FORMULA_FONT_SIZE, dpi: int = FORMULA_DPI, align: str = "left") -> str:
    """Render LaTeX to embeddable SVG HTML; return empty string on failure."""
    try:
        svg_data = render_latex_to_svg_bytes(text, font_size=font_size, dpi=dpi)
    except Exception:
        return ""
    if not svg_data:
        return ""
    return _image_block_html(mime_type="image/svg+xml", payload=svg_data, align=align)


def latex_image_html(
    text: object,
    *,
    prefer_svg: bool = True,
    font_size: int = FORMULA_FONT_SIZE,
    dpi: int = FORMULA_DPI,
    align: str = "left",
) -> str:
    """Render LaTeX as embeddable HTML image; prefer SVG and fall back to PNG."""
    if prefer_svg:
        rendered = latex_svg_html(text, font_size=font_size, dpi=dpi, align=align)
        if rendered:
            return rendered
    try:
        png_data = render_latex_to_png_bytes(text, font_size=font_size, dpi=dpi)
    except Exception:
        return ""
    if not png_data:
        return ""
    return _image_block_html(mime_type="image/png", payload=png_data, align=align)


def safe_formula_html(
    text: object,
    *,
    prefer_svg: bool = True,
    align: str = "left",
    font_size: int = FORMULA_FONT_SIZE,
) -> str:
    """Render math as LaTeX image and descriptive text as normal readable HTML."""
    value = str(text or "").strip()
    if not value:
        return ""
    if is_renderable_latex_formula(value):
        lines = split_latex_formula_for_display(value)
        if len(lines) > 1:
            rendered_lines = latex_lines_to_html(
                lines,
                prefer_svg=prefer_svg,
                align=align,
                font_size=font_size,
                separate_lines=True,
            )
            if rendered_lines:
                return rendered_lines
        rendered = latex_image_html(value, prefer_svg=prefer_svg, align=align, font_size=font_size)
        if rendered:
            return rendered
    return readable_formula_html(value, align=align)


def readable_formula_html(text: object, *, align: str = "left") -> str:
    value = readable_formula_text(text)
    return (
        "<div class='formula-readable-text' "
        f"style='margin:3px 0; padding:3px 0; width:100%; text-align:{align}; "
        "font-family:Segoe UI, Arial, sans-serif; font-size:12pt; line-height:1.25; "
        "white-space:pre-wrap; word-break:break-word; color:#0f172a;'>"
        f"{escape(value)}"
        "</div>"
    )


def readable_formula_lines_html(
    lines: list[str] | tuple[str, ...],
    *,
    align: str = "left",
    compact: bool = False,
) -> str:
    rows: list[str] = []
    for index, line in enumerate(lines):
        value = readable_formula_text(line)
        if index > 0 and value.startswith("·"):
            value = "  " + value
        rows.append(
            "<div class='formula-readable-line' "
            f"style='margin:{'2px' if compact else '3px'} 0; padding:2px 0; "
            f"text-align:{align}; font-family:Segoe UI, Arial, sans-serif; "
            "font-size:12pt; line-height:1.25; white-space:pre-wrap; "
            "word-break:break-word; color:#0f172a;'>"
            f"{escape(value)}"
            "</div>"
        )
    return "<div class='formula-readable-lines' style='width:100%;'>" + "".join(rows) + "</div>"


def formula_section_html(title: object, rows_html: str) -> str:
    """Wrap a group of formula rows with the shared compact section style."""
    if not rows_html:
        return ""
    return f"<div style='{FORMULA_SECTION_STYLE}'>{escape(str(title))}</div>{rows_html}"


def formula_item_html(
    label: object,
    formula_html: str,
    *,
    numeric_value: object = None,
    comment: object = "",
) -> str:
    """Wrap one rendered formula with the same card style everywhere."""
    numeric = ""
    if numeric_value not in (None, ""):
        numeric = f"<div style='{FORMULA_META_STYLE}'>Значение: {escape(str(numeric_value))}</div>"
    comment_html = f"<div style='{FORMULA_META_STYLE}'>{escape(str(comment))}</div>" if comment else ""
    return (
        f"<div style='{FORMULA_CARD_STYLE}'>"
        f"<div style='{FORMULA_LABEL_STYLE}'>{escape(str(label))}</div>"
        f"{formula_html}"
        f"{numeric}"
        f"{comment_html}"
        "</div>"
    )


def _svg_length_to_float(value: str) -> float:
    match = re.match(r"^\s*([0-9]+(?:\.[0-9]+)?)", str(value or ""))
    return float(match.group(1)) if match else 0.0


def _svg_dimensions(svg_data: bytes) -> tuple[float, float, str]:
    root = ET.fromstring(svg_data)
    width = _svg_length_to_float(root.attrib.get("width", "0"))
    height = _svg_length_to_float(root.attrib.get("height", "0"))
    view_box = str(root.attrib.get("viewBox", "")).strip()
    if (width <= 0 or height <= 0) and view_box:
        try:
            _, _, width_value, height_value = [float(part) for part in view_box.split()]
            width = width or width_value
            height = height or height_value
        except ValueError:
            pass
    if not view_box:
        view_box = f"0 0 {max(width, 1.0)} {max(height, 1.0)}"
    return max(width, 1.0), max(height, 1.0), view_box


def render_latex_lines_to_png_bytes(
    lines: list[str] | tuple[str, ...],
    *,
    font_size: int = FORMULA_FONT_SIZE,
    dpi: int = FORMULA_DPI,
    line_gap: int = FORMULA_LINE_GAP,
    padding: int = FORMULA_PADDING,
) -> bytes:
    """Render multiple LaTeX lines into a single PNG using one shared font size."""
    rendered_lines = [str(line or "").strip() for line in lines if str(line or "").strip()]
    if not rendered_lines:
        return b""
    if len(rendered_lines) == 1:
        return render_latex_to_png_bytes(rendered_lines[0], font_size=font_size, dpi=dpi)

    images: list[Image.Image] = []
    for line in rendered_lines:
        png_data = render_latex_to_png_bytes(line, font_size=font_size, dpi=dpi)
        if not png_data:
            continue
        with Image.open(io.BytesIO(png_data)) as image:
            images.append(image.convert("RGBA"))

    if not images:
        return b""

    width = max(image.width for image in images) + padding * 2
    height = sum(image.height for image in images) + max(0, len(images) - 1) * line_gap + padding * 2
    combined = Image.new("RGBA", (width, height), (255, 255, 255, 0))

    y = padding
    for image in images:
        combined.alpha_composite(image, (padding, y))
        y += image.height + line_gap

    buffer = io.BytesIO()
    combined.save(buffer, format="PNG")
    return buffer.getvalue()


def render_latex_lines_to_svg_bytes(
    lines: list[str] | tuple[str, ...],
    *,
    font_size: int = FORMULA_FONT_SIZE,
    dpi: int = FORMULA_DPI,
    line_gap: int = FORMULA_LINE_GAP,
    padding: int = FORMULA_PADDING,
) -> bytes:
    """Render multiple LaTeX lines into a single SVG using shared sizing."""
    rendered_lines = [str(line or "").strip() for line in lines if str(line or "").strip()]
    if not rendered_lines:
        return b""
    if len(rendered_lines) == 1:
        return render_latex_to_svg_bytes(rendered_lines[0], font_size=font_size, dpi=dpi)

    line_svgs: list[tuple[bytes, float, float, str]] = []
    for line in rendered_lines:
        svg_data = render_latex_to_svg_bytes(line, font_size=font_size, dpi=dpi)
        if not svg_data:
            continue
        width, height, view_box = _svg_dimensions(svg_data)
        line_svgs.append((svg_data, width, height, view_box))

    if not line_svgs:
        return b""

    total_width = max(width for _, width, _, _ in line_svgs) + padding * 2
    total_height = sum(height for _, _, height, _ in line_svgs) + max(0, len(line_svgs) - 1) * line_gap + padding * 2
    root = ET.Element("svg", {
        "xmlns": SVG_NS,
        "width": f"{total_width}",
        "height": f"{total_height}",
        "viewBox": f"0 0 {total_width} {total_height}",
    })

    y = float(padding)
    for svg_data, width, height, view_box in line_svgs:
        image = ET.SubElement(root, "image", {
            "x": str(padding),
            "y": str(y),
            "width": str(width),
            "height": str(height),
            "preserveAspectRatio": "xMinYMin meet",
            "href": f"data:image/svg+xml;base64,{base64.b64encode(svg_data).decode('ascii')}",
        })
        image.set("data-viewBox", view_box)
        y += height + line_gap

    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def latex_lines_to_html(
    lines: list[str] | tuple[str, ...],
    *,
    compact: bool = False,
    font_size: int | None = None,
    dpi: int = FORMULA_DPI,
    prefer_svg: bool = True,
    align: str = "left",
    separate_lines: bool = False,
) -> str:
    """Render multiple LaTeX lines as one HTML image block with uniform sizing."""
    rendered_lines = [str(line or "").strip() for line in lines if str(line or "").strip()]
    if not rendered_lines:
        return ""

    resolved_font_size = font_size or FORMULA_FONT_SIZE
    resolved_gap = 8 if compact else FORMULA_LINE_GAP
    resolved_padding = 2 if compact else FORMULA_PADDING
    margin = "0" if compact else "3px 0"

    if separate_lines:
        line_margin = "1px 0" if compact else "2px 0"
        rendered_blocks = [
            latex_image_html(
                line,
                prefer_svg=prefer_svg,
                font_size=resolved_font_size,
                dpi=dpi,
                align=align,
            ).replace("margin:6px 0;", f"margin:{line_margin};")
            for line in rendered_lines
        ]
        rendered_blocks = [block for block in rendered_blocks if block]
        if rendered_blocks:
            return (
                f"<div class='formula-latex-lines' style='margin:{margin}; width:100%; text-align:{align};'>"
                + "".join(rendered_blocks)
                + "</div>"
            )

    if prefer_svg:
        try:
            svg_data = render_latex_lines_to_svg_bytes(
                rendered_lines,
                font_size=resolved_font_size,
                dpi=dpi,
                line_gap=resolved_gap,
                padding=resolved_padding,
            )
        except Exception:
            svg_data = b""
        if svg_data:
            return _image_block_html(mime_type="image/svg+xml", payload=svg_data, margin=margin, align=align)

    try:
        png_data = render_latex_lines_to_png_bytes(
            rendered_lines,
            font_size=resolved_font_size,
            dpi=dpi,
            line_gap=resolved_gap,
            padding=resolved_padding,
        )
    except Exception:
        png_data = b""

    if png_data:
        return _image_block_html(mime_type="image/png", payload=png_data, margin=margin, align=align)

    font_size_css = "10pt"
    margin_css = "1px 0" if compact else "3px 0"
    return (
        "<pre style='white-space:pre-wrap; word-break:break-word; "
        f"font-family:Consolas,monospace; font-size:{font_size_css}; margin:{margin_css}; width:100%; text-align:{align};'>"
        f"{escape(chr(10).join(rendered_lines))}</pre>"
    )


def latex_to_html(latex: object, *, prefer_svg: bool = True, align: str = "left") -> str:
    """Render LaTeX as HTML image with SVG-first fallback to PNG/plain text."""
    text = str(latex or "")
    if not text:
        return ""
    if not is_renderable_latex_formula(text):
        return readable_formula_html(text, align=align)
    lines = split_latex_formula_for_display(text)
    if len(lines) > 1:
        rendered_lines = latex_lines_to_html(lines, prefer_svg=prefer_svg, align=align, separate_lines=True)
        if rendered_lines:
            return rendered_lines
    rendered = latex_image_html(text, prefer_svg=prefer_svg, align=align)
    if rendered:
        return rendered
    return (
        "<div class='formula-latex'>"
        "<pre style='white-space:pre-wrap; word-break:break-word; "
        f"font-family:Consolas,monospace; font-size:10pt; margin:3px 0; width:100%; text-align:{align};'>"
        f"{escape(text)}</pre>"
        "</div>"
    )


def readable_formula_text(text: object) -> str:
    """Convert project LaTeX-like formula strings to stable readable math text."""
    result = str(text or "")
    result = result.replace("\\left", "").replace("\\right", "")
    result = re.sub(r"\\(?:text|mathrm)\{([^{}]*)\}", r"\1", result)
    result = re.sub(r"\\(?:text|mathrm)([A-Za-zА-Яа-я0-9_]+)", r"\1", result)

    fraction_pattern = re.compile(r"\\frac\{([^{}]+)\}\{([^{}]+)\}")
    while True:
        updated = fraction_pattern.sub(r"(\1) / (\2)", result)
        if updated == result:
            break
        result = updated

    indexed_replacements = {
        r"T_0": "T0",
        r"T_v": "Tв",
        r"T_{v1}": "Tв1",
        r"T_{v2}": "Tв2",
        r"T_{vi}": "Tвi",
        r"T_{vj}": "Tвj",
        r"T_{upr}": "Tупр",
        r"T_{pr}": "Tпр",
        r"t_{доп}": "tдоп",
        r"T_{ВН}": "Tвн",
        r"T_{РІРЅ}": "Tвн",
        r"K_g": "Kг",
        r"K_{og}": "Kог",
        r"K_{upr}": "Kупр",
        r"K_{o,upr}": "Kо,упр",
        r"\lambda_1": "λ1",
        r"\lambda_2": "λ2",
        r"\lambda_3": "λ3",
        r"\lambda_p": "λп",
        r"\lambda_s": "λs",
        r"\lambda_{upr}": "λупр",
        r"\lambda": "λ",
        r"\gamma": "γ",
    }
    for source, target in indexed_replacements.items():
        result = result.replace(source, target)

    replacements = {
        r"\sum": "Σ",
        r"\prod": "Π",
        r"\Sigma": "Σ",
        r"\Pi": "Π",
        r"\cdot": "·",
        r"\quad": "  ",
        r"\lfloor": "⌊",
        r"\rfloor": "⌋",
        r"\ldots": "...",
        r"\text": "",
        r"\mathrm": "",
        r"\;": " ",
        r"\,": " ",
    }
    for source, target in replacements.items():
        result = result.replace(source, target)

    result = result.replace("^", "^")
    result = result.replace("{", "").replace("}", "")
    result = re.sub(r"\s+", " ", result).strip()
    return result


def formula_dict_to_plain(formulas: dict[str, str]) -> str:
    """Render named formulas as plain text suitable for TXT/DOCX/XLSX."""
    return "\n".join(f"{name}: {readable_formula_text(value)}" for name, value in formulas.items())


class FormulaRenderer:
    """Render a FormulaPackage without choosing or modifying its calculation method."""

    @classmethod
    def render(cls, package):
        """Fill all public render fields on a FormulaPackage and return it."""
        renderer = cls()
        for item in package.formulas + package.intermediate_formulas + package.result_formulas:
            renderer._ensure_formula_item_rendering(item)
        package.plain_text = renderer.to_plain_text(package)
        package.latex_text = renderer.to_latex_text(package)
        package.html_text = renderer.to_html(package)
        package.export_payload = renderer.to_export_payload(package)
        return package

    def to_plain_text(self, package) -> str:
        lines = [
            package.title,
            f"режим формулы: {self._formula_mode_label(package.formula_mode)}",
            f"нормативная формула: {'да' if package.is_normative else 'нет'}",
            f"источник: {package.source_label}",
        ]
        if package.applicability:
            lines.append(f"область применения: {package.applicability}")
        if package.limitations:
            lines.append(f"ограничения: {package.limitations}")
        if package.parameter_lines:
            lines.extend(["", "Параметры:"])
            lines.extend(
                f"- {item.name} = {item.value}{(' ' + item.unit) if item.unit else ''}"
                for item in sorted(package.parameter_lines, key=lambda item: item.order)
            )
        for title, items in (
            ("Формулы", package.formulas),
            ("Промежуточные формулы", package.intermediate_formulas),
            ("Формулы результатов", package.result_formulas),
        ):
            if not items:
                continue
            lines.extend(["", f"{title}:"])
            lines.extend(self._plain_formula_line(item) for item in sorted(items, key=lambda item: item.order))
        if package.numeric_results:
            lines.extend(["", "Численные результаты:"])
            lines.extend(f"- {key} = {value}" for key, value in package.numeric_results.items())
        if package.warnings:
            lines.extend(["", "Предупреждения:"])
            lines.extend(f"- {warning}" for warning in package.warnings)
        return "\n".join(str(line) for line in lines if line is not None)

    def to_latex_text(self, package) -> str:
        lines = [package.title]
        for section_title, items in (
            ("Формулы", package.formulas),
            ("Промежуточные формулы", package.intermediate_formulas),
            ("Формулы результатов", package.result_formulas),
        ):
            if not items:
                continue
            lines.extend(["", section_title + ":"])
            for item in sorted(items, key=lambda value: value.order):
                formula = item.instantiated_latex or item.display_latex or item.general_latex
                if formula:
                    lines.append(f"- {item.label}: {latex_block(formula)}")
                elif item.instantiated_formula or item.symbolic_template:
                    lines.append(f"- {item.label}: {latex_block(item.instantiated_formula or item.symbolic_template)}")
        return "\n".join(lines)

    def to_html(self, package) -> str:
        formula_blocks = "".join(
            self._html_formula_section(title, items)
            for title, items in (
                ("Основные формулы", package.formulas),
                ("Промежуточные формулы", package.intermediate_formulas),
                ("Формулы результатов", package.result_formulas),
            )
            if items
        )
        warnings = "".join(f"<li>{escape(str(warning))}</li>" for warning in package.warnings)
        return (
            f"<h3>{escape(str(package.title))}</h3>"
            f"<p><b>Режим формулы:</b> {escape(self._formula_mode_label(package.formula_mode))}<br>"
            f"<b>Нормативная формула:</b> {escape('да' if package.is_normative else 'нет')}<br>"
            f"<b>Источник:</b> {escape(str(package.source_label))}</p>"
            f"<p><b>Область применения:</b> {escape(str(package.applicability or '-'))}</p>"
            f"<p><b>Ограничения:</b> {escape(str(package.limitations or '-'))}</p>"
            f"{formula_blocks or '<p>Формулы недоступны.</p>'}"
            f"{'<p><b>Предупреждения:</b></p><ul>' + warnings + '</ul>' if warnings else ''}"
        )

    def to_export_payload(self, package) -> dict[str, Any]:
        return {
            "formula_mode": package.formula_mode,
            "is_normative": package.is_normative,
            "method_code": package.method_code,
            "title": package.title,
            "source_label": package.source_label,
            "source_details": package.source_details,
            "applicability": package.applicability,
            "limitations": package.limitations,
            "warnings": list(package.warnings),
            "formulas": [asdict(item) for item in package.formulas],
            "intermediate_formulas": [asdict(item) for item in package.intermediate_formulas],
            "result_formulas": [asdict(item) for item in package.result_formulas],
            "parameter_lines": [asdict(item) for item in package.parameter_lines],
            "numeric_results": dict(package.numeric_results),
            "latex_text": package.latex_text,
            "metadata": dict(package.metadata),
        }

    def _ensure_formula_item_rendering(self, item) -> None:
        source = item.instantiated_formula or item.symbolic_template
        if not item.general_latex:
            item.general_latex = latex_formula_text(item.symbolic_template)
        if not item.instantiated_latex:
            item.instantiated_latex = latex_formula_text(source)
        if not item.display_latex:
            item.display_latex = item.instantiated_latex or item.general_latex
        if not item.plain_text:
            item.plain_text = readable_formula_text(source)
        if not item.html_text:
            item.html_text = self._html_formula_line(item)

    def _plain_formula_line(self, item) -> str:
        formula = item.plain_text or readable_formula_text(item.instantiated_formula or item.symbolic_template)
        suffix = f" = {item.numeric_value}" if item.numeric_value not in (None, "") else ""
        comment = f" ({item.comment})" if item.comment else ""
        return f"- {item.label}: {formula}{suffix}{comment}"

    def _html_formula_line(self, item) -> str:
        formula = item.instantiated_latex or item.display_latex or item.general_latex or latex_formula_text(item.instantiated_formula or item.symbolic_template)
        return formula_item_html(
            item.label,
            latex_to_html(latex_block(formula)),
            numeric_value=item.numeric_value,
            comment=item.comment,
        )

    def _html_formula_section(self, title: str, items) -> str:
        rows = "".join(self._html_formula_line(item) for item in sorted(items, key=lambda item: item.order))
        return formula_section_html(title, rows)

    def _formula_mode_label(self, mode: object) -> str:
        labels = {
            "normative": "нормативная методика",
            "structural_fallback": "структурная композиционная формула",
            "algorithmic": "алгоритмический режим",
        }
        return labels.get(str(mode), str(mode))


def formula_dict_to_html(formulas: dict[str, str]) -> str:
    """Render named formulas as compact HTML blocks."""
    if not formulas:
        return "<span style='color:#8a4b18;'>Формула не задана.</span>"
    return "".join(
        formula_item_html(name, safe_formula_html(value))
        for name, value in formulas.items()
    )


def result_metric_formulas_for(result_keys: list[str] | tuple[str, ...] | set[str]) -> dict[str, str]:
    """Return formulas/explanations for result indicators that are actually shown."""
    return {key: RESULT_METRIC_FORMULAS[key] for key in result_keys if key in RESULT_METRIC_FORMULAS}


def result_metric_latex_for(result_keys: list[str] | tuple[str, ...] | set[str]) -> dict[str, str]:
    """Return LaTeX formulas/explanations for result indicators that are actually shown."""
    return {key: RESULT_METRIC_LATEX[key] for key in result_keys if key in RESULT_METRIC_LATEX}
