import app.core.dependability_backend as backend
import app.formulas.formula_rendering as rendering

from app.formulas.formula_package import generate_formula_package
from app.formulas.formula_rendering import is_renderable_latex_formula, latex_image_html, latex_lines_to_html, latex_to_html, normalize_latex_for_mathtext, safe_formula_html, readable_latex_lines_for_display, split_latex_formula_for_display
from app.core.rbd_models import BlockModel, ConnectionModel, FormulaItem, SchemeModel


def _series_scheme(count: int = 3) -> SchemeModel:
    blocks = [BlockModel("start", "Start", "in", 0, 0, {})]
    connections = []
    previous = "start"
    for index in range(1, count + 1):
        block_id = f"b{index}"
        blocks.append(BlockModel(block_id, f"B{index}", "right", index * 100, 0, {"lambda": 0.001 * index}))
        connections.append(ConnectionModel(f"c{index}", previous, "right", block_id, "left"))
        previous = block_id
    blocks.append(BlockModel("end", "End", "out", 100 * (count + 1), 0, {}))
    connections.append(ConnectionModel("c_end", previous, "right", "end", "in"))
    return SchemeModel("Series", blocks, connections)


def _parallel_scheme() -> SchemeModel:
    return SchemeModel(
        "Parallel",
        [
            BlockModel("start", "Start", "in", 0, 100, {}),
            BlockModel("split", "Split", "junction", 100, 100, {}),
            BlockModel("p1", "P1", "right", 200, 60, {"lambda": 0.001}),
            BlockModel("p2", "P2", "right", 200, 120, {"lambda": 0.002}),
            BlockModel("join", "Join", "junction", 300, 100, {}),
            BlockModel("end", "End", "out", 400, 100, {}),
        ],
        [
            ConnectionModel("c_start", "start", "out", "split", "left"),
            ConnectionModel("c1", "split", "right", "p1", "left"),
            ConnectionModel("c2", "p1", "right", "join", "left"),
            ConnectionModel("c3", "split", "right", "p2", "left"),
            ConnectionModel("c4", "p2", "right", "join", "left"),
            ConnectionModel("c_end", "join", "right", "end", "in"),
        ],
    )


def _reserve_scheme() -> SchemeModel:
    return SchemeModel(
        "Reserve",
        [
            BlockModel("start", "Start", "in", 0, 0, {}),
            BlockModel("r", "R", "right", 100, 0, {"lambda": 0.001, "reserve_count": 2}),
            BlockModel("end", "End", "out", 200, 0, {}),
        ],
        [
            ConnectionModel("c1", "start", "out", "r", "left"),
            ConnectionModel("c2", "r", "right", "end", "in"),
        ],
    )


def test_formula_item_has_latex_fields():
    item = FormulaItem("x", "X", "Pсист = A · B")
    assert hasattr(item, "general_latex")
    assert hasattr(item, "instantiated_latex")
    assert hasattr(item, "display_latex")


def test_series_package_uses_latex_as_canonical_formula_output():
    package = generate_formula_package(scheme=_series_scheme(3), time_horizon=100)

    assert package.latex_text
    assert r"\cdot" in package.latex_text
    assert r"P_{\mathrm{b1}}" in package.latex_text
    assert "AUTO.COMPOSITION" not in package.latex_text
    assert package.export_payload["latex_text"] == package.latex_text
    assert any(item.instantiated_latex for item in package.intermediate_formulas)


def test_parallel_package_contains_latex_parallel_formula():
    package = generate_formula_package(scheme=_parallel_scheme(), time_horizon=100)

    assert "1 - " in package.latex_text
    assert r"P_{\mathrm{p1}}" in package.latex_text
    assert r"P_{\mathrm{p2}}" in package.latex_text


def test_reserve_package_contains_latex_power():
    package = generate_formula_package(scheme=_reserve_scheme(), time_horizon=100)

    assert "^{3}" in package.latex_text
    assert any(item.formula_id == "STRUCT.RESERVE.P" for item in package.intermediate_formulas)


def test_f22_normative_branch_has_required_latex_formulas():
    inputs = {"cat3_f22": 1, "t": 100, "n": 2, "m": 1, "t_v": 6.0, "lam": 0.001, "lam_p": 0.0005, "lam_s": 0.0}
    result = backend.f22(cat3=1, t=inputs["t"], n=inputs["n"], m=inputs["m"], t_v=inputs["t_v"], lam=inputs["lam"], lam_p=inputs["lam_p"], lam_s=inputs["lam_s"])
    package = generate_formula_package(method_code="F2.2", inputs=inputs, numeric_results=result)

    assert r"\frac{t_" in package.latex_text
    assert r"\frac{T_0}" in package.latex_text
    assert r"\cdot P" in package.latex_text


def test_f63_latex_keeps_t0_limitation():
    result = backend.f63(t=100, r1=3, r2=2, r3=2, m=2, lam1=0.001, lam2=0.002, lam3=0.003, t_upr=1000)
    package = generate_formula_package(
        method_code="F6.3",
        inputs={"t": 100, "r1": 3, "r2": 2, "r3": 2, "m": 2, "lam1": 0.001, "lam2": 0.002, "lam3": 0.003, "t_upr": 1000},
        numeric_results={"P": result["P"]},
    )

    assert package.latex_text
    assert "T0" in package.limitations
    assert all(item.label != "T0" for item in package.result_formulas)


def test_latex_html_renderer_builds_embedded_image_for_simple_formula():
    html = latex_to_html(r"\[ P_{\text{сист}}(t) = P_1 \cdot P_2 \]")

    assert "data:image/svg+xml;base64," in html
    assert "<img " in html


def test_latex_renderability_filter_keeps_descriptive_text_out_of_mathtext():
    assert is_renderable_latex_formula(r"P_{\text{sys}} \cdot P_2")
    assert is_renderable_latex_formula(r"K_{\text{г}} = \frac{T_0}{T_0 + T_{\text{в}}}")
    assert is_renderable_latex_formula(r"e^{-\lambda t}")
    assert not is_renderable_latex_formula("Последовательно(Блок_1, Блок_2)")
    assert not is_renderable_latex_formula("последовательно: произведение; параллельно: правило отказов")


def test_safe_formula_html_uses_text_block_for_non_latex_description():
    html = safe_formula_html("Последовательно(Блок_1, Блок_2)")

    assert "formula-readable-text" in html
    assert "<img " not in html


def test_multiline_latex_renderer_uses_single_embedded_image_with_uniform_sizing():
    html = latex_lines_to_html(
        [
            r"P_{\text{сист}}(t) = (1 - P_{\text{B1}})",
            r"(1 - P_{\text{B2}})(1 - P_{\text{B3}})",
        ],
        compact=True,
    )

    assert html.count("<img ") == 1
    assert "data:image/svg+xml;base64," in html


def test_latex_lines_to_html_supports_left_aligned_layout():
    html = latex_lines_to_html(
        [r"P_{\text{сист}}(t) = P_1 \cdot P_2"],
        compact=True,
        align="left",
    )

    assert "text-align:left" in html
    assert "width:100%" in html


def test_latex_lines_to_html_can_render_separate_readable_line_images():
    html = latex_lines_to_html(
        [
            r"P_{\text{sys}} = P_1 \cdot P_2",
            r"\cdot P_3 \cdot P_4",
        ],
        font_size=18,
        separate_lines=True,
    )

    assert html.count("<img ") == 2
    assert "formula-latex-lines" in html
    assert "overflow-x:auto" in html
    assert "max-width:none; height:auto; vertical-align:middle;" in html


def test_multiline_latex_to_html_keeps_math_renderer_instead_of_plain_text():
    formula = (
        r"P_{\text{сист}}(t) = P_{B1} \cdot P_{B2A} \cdot P_{B2B} \cdot P_{B2C} "
        r"\cdot P_{B2D} \cdot P_{B3} \cdot P_{B4} \cdot P_{B5} \cdot P_{B6}"
    )

    html = latex_to_html(formula)

    assert "formula-latex-lines" in html
    assert "<img " in html
    assert "formula-readable-lines" not in html
    assert r"\cdot" not in html
    assert "P_{B2A}" not in html


def test_fraction_latex_to_html_keeps_frac_command_renderable():
    html = latex_to_html(r"K_{\text{г}} = \frac{T_0}{T_0 + T_{\text{в}}}")

    assert "<img " in html
    assert "data:image/svg+xml;base64," in html
    assert r"\frac" not in html


def test_safe_formula_html_renders_compact_block_symbols_as_latex():
    html = safe_formula_html(r"K_{\text{г,сист}} = K_{B1} \cdot K_{B2A}")

    assert "<img " in html
    assert "formula-readable-text" not in html
    assert "K_{B2A}" not in html


def test_latex_image_html_falls_back_to_png_when_svg_rendering_fails(monkeypatch):
    monkeypatch.setattr(rendering, "render_latex_to_svg_bytes", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("svg fail")))

    html = latex_image_html(r"P_{\text{сист}}(t)=P_1", prefer_svg=True)

    assert "data:image/png;base64," in html


def test_latex_png_html_contains_explicit_dimensions_for_qtextedit():
    html = latex_image_html(r"P_{\text{sys}}=P_1", prefer_svg=False, font_size=22)

    assert "data:image/png;base64," in html
    assert " width='" in html
    assert " height='" in html
    assert "max-width:none; height:auto; vertical-align:middle;" in html


def test_long_latex_product_is_split_for_readable_display():
    formula = r"P_{\text{sys}} = P_1 \cdot P_2 \cdot P_3 \cdot P_4 \cdot P_5 \cdot P_6 \cdot P_7"

    lines = split_latex_formula_for_display(formula, max_line_length=42)

    assert len(lines) > 1
    assert lines[0].startswith(r"P_{\text{sys}} = P_1")
    assert any(line.startswith(r"\cdot ") for line in lines[1:])


def test_latex_splitter_keeps_nested_frac_text_and_indices_intact():
    formula = (
        r"P_{\text{sys}} = \frac{A_1 + B_1}{C_1 - D_1} \cdot "
        r"P_{\text{block_long_name}} \cdot \text{manual verification required}"
    )

    lines = split_latex_formula_for_display(formula, max_line_length=58)

    assert len(lines) > 1
    assert any(r"\frac{A_1 + B_1}{C_1 - D_1}" in line for line in lines)
    assert any(r"P_{\text{block_long_name}}" in line for line in lines)
    assert any(r"\text{manual verification required}" in line for line in lines)


def test_readable_latex_lines_for_display_removes_raw_latex_commands():
    formula = (
        r"P_{\text{sys}} = \frac{A_1 + B_1}{C_1 - D_1} \cdot "
        r"P_{\text{block_long_name}} \cdot P_3 \cdot P_4"
    )

    lines = readable_latex_lines_for_display(formula, max_line_length=58)
    rendered = "\n".join(lines)

    assert len(lines) > 1
    assert r"\text" not in rendered
    assert r"\frac" not in rendered
    assert r"\cdot" not in rendered
    assert "·" in rendered
    assert any(line.lstrip().startswith("·") for line in lines[1:])


def test_f21_normative_package_keeps_original_latex_without_readable_text_damage():
    package = generate_formula_package(
        method_code="F2.1",
        inputs={"cat3_f2": 1, "t": 1000, "n": 2, "lam_list": [0.001, 0.001], "tv_list": [10.0, 10.0], "t_0_list": [1000.0, 1000.0]},
        numeric_results={"T0": 500.0, "Tv": 10.05, "Kg": 0.9802960494069208, "Kog": 0.1326686435022181, "P": 0.1353352832366127},
    )

    main_formula = package.formulas[0].instantiated_latex
    assert r"\frac{1}{1+\lambda_i T_{vi}}" in main_formula
    assert r"e^{-t/T_{0i}}" in main_formula
    assert r"\frac11+" not in main_formula


def test_normalize_latex_for_mathtext_preserves_spaces_inside_text_blocks():
    normalized = normalize_latex_for_mathtext(r"T_0 = \text{mean time to failure}")

    assert normalized == r"T_0 = \mathrm{mean\ time\ to\ failure}"


def test_normalize_latex_for_mathtext_keeps_trailing_text_space_before_variable():
    normalized = normalize_latex_for_mathtext(r"P(t) = \text{probability over time } t")

    assert normalized == r"P(t) = \mathrm{probability\ over\ time\ } t"


def test_structural_reserve_formula_uses_renderable_latex_for_main_formula():
    package = generate_formula_package(scheme=_reserve_scheme(), time_horizon=100)
    main_formula = package.formulas[0].instantiated_latex

    assert r"P_{\text{сист}}(t)" in main_formula
    assert r"P_{\mathrm{r}}" in main_formula
    assert "data:image/svg+xml;base64," in latex_to_html(main_formula)


def test_long_block_names_stay_in_symbols_not_latex_formula_html():
    scheme = SchemeModel(
        "Long names",
        [
            BlockModel("start", "Start", "in", 0, 0, {}),
            BlockModel("B1", "Внутренний участок цепи собственных нужд 1", "right", 100, 0, {"lambda": 0.001}),
            BlockModel("B2A", "Внутренний участок цепи собственных нужд 2", "right", 200, 0, {"lambda": 0.002}),
            BlockModel("end", "End", "out", 300, 0, {}),
        ],
        [
            ConnectionModel("c1", "start", "out", "B1", "left"),
            ConnectionModel("c2", "B1", "right", "B2A", "left"),
            ConnectionModel("c3", "B2A", "right", "end", "in"),
        ],
    )

    package = generate_formula_package(scheme=scheme, time_horizon=100)
    formula_latex = "\n".join(item.instantiated_latex for item in package.formulas)
    symbols = package.metadata.get("symbols", {})

    assert "B1" in formula_latex
    assert "B2A" in formula_latex
    assert "Внутренний участок цепи собственных нужд" not in formula_latex
    assert any("Внутренний участок цепи собственных нужд 1" in text for text in symbols.values())
    assert "<img " in package.html_text
    assert r"\cdot" not in package.html_text
