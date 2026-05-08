from app.formulas.formula_rendering import readable_formula_text
from app.core.normative_methods import SUPPORTED_METHODS_BY_CODE, UNSUPPORTED_METHODS


def test_all_project_methods_available_in_registry():
    expected = {
        "F1.1", "F1.2", "F1.3", "F1.4", "F1.5",
        "F2.1", "F2.2", "F2.3", "F2.4", "F2.5", "F2.6", "F2.7",
        "F3.1", "F4.1", "F5.1",
        "F6.1", "F6.2", "F6.3",
        "F7.1", "F7.2",
    }
    assert expected.issubset(set(SUPPORTED_METHODS_BY_CODE))


def test_no_disabled_methods_after_formula_update():
    assert UNSUPPORTED_METHODS == {}


def test_f63_keeps_documented_limitation_note():
    assert "T0" in SUPPORTED_METHODS_BY_CODE["F6.3"].limitations


def test_result_fields_match_documented_indicator_sets():
    expected = {
        "F1.1": ("P", "T0"),
        "F1.2": ("P", "T0"),
        "F1.3": ("P", "T0"),
        "F1.4": ("P", "T0"),
        "F1.5": ("P", "T0"),
        "F2.1": ("P", "T0", "Tv", "Kg", "Kog"),
        "F2.2": ("P", "T0", "Tv", "Kg", "Kog"),
        "F2.3": ("P", "T0", "Tv", "Kg", "Kog"),
        "F2.4": ("P", "T0", "Tv", "Kg", "Kog"),
        "F2.5": ("P", "T0", "Tv", "Kg", "Kog"),
        "F2.6": ("P", "T0", "Tv", "Kg", "Kog"),
        "F2.7": ("P", "T0", "Tv", "Kg", "Kog"),
        "F3.1": ("P", "T0", "Tv", "Kg", "Kog"),
        "F4.1": ("P", "T0", "Tv", "Kg", "Kog"),
        "F5.1": ("P", "T0", "Tpr", "Kg", "Kog"),
        "F6.1": ("P", "T0"),
        "F6.2": ("P", "T0"),
        "F6.3": ("P",),
        "F7.1": ("T0", "Kg", "Kog"),
        "F7.2": ("T0", "Kg", "Kog"),
    }
    for code, fields in expected.items():
        assert SUPPORTED_METHODS_BY_CODE[code].result_fields == fields


def test_f22_registry_exposes_tv_and_kg_postprocessing():
    formulas = SUPPORTED_METHODS_BY_CODE["F2.2"].formulas
    combined = " ".join(formulas.values())
    assert "T_v" in combined
    assert "K_g" in combined
    assert "T_0+T_v" in combined


def test_all_methods_have_professional_guides():
    for spec in SUPPORTED_METHODS_BY_CODE.values():
        assert spec.description
        assert spec.calculates
        assert spec.use_when
        assert spec.example


def test_all_method_arguments_have_parameter_docs():
    for spec in SUPPORTED_METHODS_BY_CODE.values():
        missing = [arg for arg in spec.args if arg not in spec.parameter_docs]
        assert missing == []


def test_methodology_text_contains_user_facing_sections():
    for spec in SUPPORTED_METHODS_BY_CODE.values():
        text = spec.methodology_text
        assert "Описание:" in text
        assert "Что рассчитывает:" in text
        assert "Где применяется:" in text
        assert "Параметры:" in text


def test_all_output_indicators_have_user_visible_formulas():
    for spec in SUPPORTED_METHODS_BY_CODE.values():
        missing = [field for field in spec.result_fields if field not in spec.result_formulas]
        assert missing == []


def test_formula_renderer_removes_raw_latex_fraction_commands():
    rendered = readable_formula_text(r"T_0=\frac{1}{\sum_i \lambda_i}")
    assert "\\frac" not in rendered
    assert "дробь" not in rendered.lower()
    assert "T0" in rendered
    assert "λ" in rendered
