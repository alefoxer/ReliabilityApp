"""Qt-friendly formula renderer shared by editor and calculator widgets."""

from __future__ import annotations

from html import escape

from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QImage, QTextDocument
from PyQt6.QtWidgets import QTextEdit

from app.formulas.formula_rendering import (
    FORMULA_FONT_SIZE,
    formula_item_html,
    is_renderable_latex_formula,
    latex_image_html,
    latex_lines_to_html,
    readable_formula_html,
    render_latex_to_png_bytes,
    split_latex_formula_for_display,
)


class QtFormulaHtmlRenderer:
    """Render formulas for QTextEdit without data-URI sizing surprises."""

    def __init__(
        self,
        *,
        resource_prefix: str = "formula://qt",
        quality_scale: int = 2,
        fallback_svg: bool = False,
    ) -> None:
        self.resource_prefix = resource_prefix.rstrip("/")
        self.quality_scale = max(1, int(quality_scale))
        self.fallback_svg = fallback_svg
        self._counter = 0
        self._resources: list[tuple[QUrl, QImage]] = []

    def reset(self) -> None:
        self._counter = 0
        self._resources = []

    def _load_formula_image(
        self,
        line: str,
        *,
        font_size: int,
    ) -> QImage:
        try:
            png_data = render_latex_to_png_bytes(line, font_size=font_size * self.quality_scale)
        except Exception:
            png_data = b""
        image = QImage()
        if not png_data or not image.loadFromData(png_data, "PNG"):
            return QImage()
        return image

    def _fit_formula_image(
        self,
        line: str,
        *,
        font_size: int,
        max_display_width: int | None,
    ) -> tuple[QImage, int, int]:
        resolved_font_size = max(8, int(font_size))
        image = self._load_formula_image(line, font_size=resolved_font_size)
        if image.isNull():
            return image, 0, 0

        if max_display_width is not None:
            target_width = max(64, int(max_display_width))
            for _ in range(2):
                display_width = max(1, int(image.width() / self.quality_scale))
                if display_width <= target_width:
                    break
                shrink_ratio = target_width / display_width
                next_font_size = max(8, int(resolved_font_size * shrink_ratio * 0.96))
                if next_font_size >= resolved_font_size:
                    break
                refit = self._load_formula_image(line, font_size=next_font_size)
                if refit.isNull():
                    break
                resolved_font_size = next_font_size
                image = refit

        display_width = max(1, int(image.width() / self.quality_scale))
        display_height = max(1, int(image.height() / self.quality_scale))
        if max_display_width is not None and display_width > max_display_width:
            scale = max_display_width / display_width
            display_width = max(1, int(display_width * scale))
            display_height = max(1, int(display_height * scale))
        return image, display_width, display_height

    def _resolve_common_font_size(
        self,
        lines: list[str],
        *,
        font_size: int,
        max_display_width: int | None,
    ) -> int:
        resolved_font_size = max(8, int(font_size))
        if max_display_width is None:
            return resolved_font_size
        target_width = max(64, int(max_display_width))
        widest_line = max(lines, key=len, default="")
        image = self._load_formula_image(widest_line, font_size=resolved_font_size)
        if image.isNull():
            return resolved_font_size
        for _ in range(3):
            display_width = max(1, int(image.width() / self.quality_scale))
            if display_width <= target_width:
                break
            shrink_ratio = target_width / display_width
            next_font_size = max(8, int(resolved_font_size * shrink_ratio * 0.96))
            if next_font_size >= resolved_font_size:
                break
            refit = self._load_formula_image(widest_line, font_size=next_font_size)
            if refit.isNull():
                break
            resolved_font_size = next_font_size
            image = refit
        return resolved_font_size

    def set_html(self, viewer: QTextEdit, html: str) -> None:
        document = viewer.document()
        document.clear()
        for url, image in self._resources:
            document.addResource(QTextDocument.ResourceType.ImageResource, url, image)
        viewer.setHtml(html)

    def formula_dict_html(
        self,
        formulas: dict[str, str],
        *,
        font_size: int = FORMULA_FONT_SIZE,
        max_display_width: int | None = 660,
        align: str = "left",
    ) -> str:
        if not formulas:
            return "<span style='color:#8a4b18;'>Формула для графика пока не задана.</span>"
        rows: list[str] = []
        for name, value in formulas.items():
            formula_html = self.formula_value_html(value, font_size=font_size, max_display_width=max_display_width, align=align)
            rows.append(formula_item_html(name, formula_html))
        return "".join(rows)

    def formula_value_html(
        self,
        value: object,
        *,
        compact: bool = False,
        align: str = "left",
        font_size: int | None = None,
        prefer_svg: bool = False,
        max_display_width: int | None = None,
    ) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        if not is_renderable_latex_formula(text):
            return readable_formula_html(text, align="left")
        display_lines = split_latex_formula_for_display(text, max_line_length=72 if compact else 90)
        if len(display_lines) > 1:
            return self.formula_lines_html(
                display_lines,
                compact=compact,
                align=align,
                font_size=font_size,
                prefer_svg=prefer_svg,
                separate_lines=True,
                max_display_width=max_display_width,
            )
        resolved_font_size = font_size or FORMULA_FONT_SIZE
        rendered = (
            self.formula_image_html(
                text,
                font_size=resolved_font_size,
                align=align,
                margin="0" if compact else "2px 0",
                max_display_width=max_display_width,
            )
            if not prefer_svg
            else latex_image_html(text, align=align, font_size=resolved_font_size, prefer_svg=True)
        )
        return rendered or readable_formula_html(text, align="left")

    def formula_lines_html(
        self,
        lines: list[str] | tuple[str, ...],
        *,
        compact: bool = False,
        align: str = "left",
        font_size: int | None = None,
        prefer_svg: bool = True,
        separate_lines: bool = False,
        max_display_width: int | None = None,
    ) -> str:
        rendered_lines = [str(line or "").strip() for line in lines if str(line or "").strip()]
        if not rendered_lines:
            return ""
        if not any(is_renderable_latex_formula(line) for line in rendered_lines):
            return "".join(readable_formula_html(line, align="left") for line in rendered_lines)
        if separate_lines and not prefer_svg:
            resolved_font_size = font_size or FORMULA_FONT_SIZE
            margin = "0" if compact else "3px 0"
            line_margin = "0" if compact else "2px 0"
            rendered = self.formula_line_images_html(
                rendered_lines,
                font_size=resolved_font_size,
                align=align,
                margin=margin,
                line_margin=line_margin,
                max_display_width=max_display_width,
            )
            if rendered:
                return rendered
        rendered = latex_lines_to_html(
            rendered_lines,
            compact=compact,
            align=align,
            font_size=font_size,
            prefer_svg=prefer_svg,
            separate_lines=separate_lines,
        )
        if rendered:
            return rendered
        return "".join(self.formula_value_html(line, compact=compact, align=align) for line in rendered_lines)

    def formula_image_html(
        self,
        line: str,
        *,
        font_size: int,
        align: str = "left",
        margin: str = "4px 0",
        max_display_width: int | None = None,
    ) -> str:
        image, display_width, display_height = self._fit_formula_image(
            line,
            font_size=font_size,
            max_display_width=max_display_width,
        )
        if image.isNull():
            if self.fallback_svg:
                return latex_image_html(line, prefer_svg=False, font_size=font_size, align=align)
            return readable_formula_html(line, align="left")
        self._counter += 1
        url = QUrl(f"{self.resource_prefix}/{self._counter}")
        self._resources.append((url, image))
        return (
            f"<div class='formula-latex-image' style='margin:{margin}; width:100%; text-align:{align}; white-space:nowrap;'>"
            f"<img src='{escape(url.toString())}' width='{display_width}' height='{display_height}' "
            "style='vertical-align:middle; white-space:nowrap;'/>"
            "</div>"
        )

    def formula_line_images_html(
        self,
        lines: list[str],
        *,
        font_size: int,
        align: str,
        margin: str,
        line_margin: str,
        max_display_width: int | None,
    ) -> str:
        common_font_size = self._resolve_common_font_size(
            lines,
            font_size=font_size,
            max_display_width=max_display_width,
        )
        rendered_images: list[tuple[QUrl, QImage]] = []
        for line in lines:
            image, _, _ = self._fit_formula_image(
                line,
                font_size=common_font_size,
                max_display_width=None,
            )
            if image.isNull():
                return ""
            self._counter += 1
            url = QUrl(f"{self.resource_prefix}/{self._counter}")
            self._resources.append((url, image))
            rendered_images.append((url, image))
        if not rendered_images:
            return ""
        common_scale = 1.0
        if max_display_width is not None:
            widest = max(image.width() / self.quality_scale for _, image in rendered_images)
            if widest > max_display_width:
                common_scale = max_display_width / widest
        rendered: list[str] = []
        for url, image in rendered_images:
            display_width = max(1, int(image.width() / self.quality_scale * common_scale))
            display_height = max(1, int(image.height() / self.quality_scale * common_scale))
            rendered.append(
                f"<div class='formula-latex-image' style='margin:{line_margin}; width:100%; text-align:{align}; white-space:nowrap;'>"
                f"<img src='{escape(url.toString())}' width='{display_width}' height='{display_height}' "
                "style='vertical-align:middle; white-space:nowrap;'/>"
                "</div>"
            )
        return (
            f"<div class='formula-latex-lines' style='margin:{margin}; width:100%; text-align:{align}; white-space:nowrap;'>"
            + "".join(rendered)
            + "</div>"
        )
