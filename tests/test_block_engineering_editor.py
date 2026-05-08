from pathlib import Path

from app.core.dependability_graph import Graph
from app.formulas.formula_engine import FormulaGenerationService
from app.core.rbd_models import BlockModel, ConnectionModel, SchemeModel
from app.core.scheme_method_selector import select_method_for_scheme
from app.import_export.scheme_storage import save_scheme, load_scheme
from app.core.validators import validate_scheme


def test_block_props_dialog_source_contains_engineering_block_types():
    root = Path(__file__).resolve().parents[1]
    source = (root / 'app' / 'gui' / 'gui_dialogs.py').read_text(encoding="utf-8")

    assert '("ordinary", "Обычный элемент")' in source
    assert '("reserve", "Элемент с резервом")' in source
    assert '("k_of_n", "k из N / скользящий резерв")' in source
    assert '("subscheme", "Подсхема")' in source
    assert '("passive", "Служебный/пассивный")' in source
    assert 'self.type_combo = QComboBox()' in source
    assert '"block_role": role' in source


def test_scheme_storage_preserves_string_engineering_params(tmp_path: Path):
    path = tmp_path / "engineering_scheme.json"
    scheme = SchemeModel(
        name="Engineering",
        blocks=[
            BlockModel("start", "Start", "in", 0, 0, {}),
            BlockModel(
                "r",
                "Reserve",
                "right",
                100,
                0,
                {"lambda": 0.001, "block_role": "k_of_n", "reserve_type": "sliding", "k_required": 2, "n_total": 3},
            ),
            BlockModel("end", "End", "out", 200, 0, {}),
        ],
        connections=[
            ConnectionModel("c1", "start", "out", "r", "left"),
            ConnectionModel("c2", "r", "right", "end", "in"),
        ],
    )

    save_scheme(path, scheme)
    restored = load_scheme(path)
    params = restored.block_by_id("r").params

    assert params["block_role"] == "k_of_n"
    assert params["reserve_type"] == "sliding"
    assert params["k_required"] == 2
    assert params["n_total"] == 3


def test_validate_scheme_rejects_invalid_k_of_n_block():
    scheme = SchemeModel(
        name="BrokenKofN",
        blocks=[
            BlockModel("start", "Start", "in", 0, 0, {}),
            BlockModel(
                "r",
                "Reserve",
                "right",
                100,
                0,
                {"lambda": 0.001, "block_role": "k_of_n", "k_required": 4, "n_total": 3},
            ),
            BlockModel("end", "End", "out", 200, 0, {}),
        ],
        connections=[
            ConnectionModel("c1", "start", "out", "r", "left"),
            ConnectionModel("c2", "r", "right", "end", "in"),
        ],
    )

    result = validate_scheme(scheme)

    assert not result.ok
    assert any("k_required" in error and "n_total" in error for error in result.errors)


def test_formula_engine_treats_explicit_k_of_n_role_as_special_case():
    scheme = SchemeModel(
        name="ExplicitKofN",
        blocks=[
            BlockModel("start", "Start", "in", 0, 0, {}),
            BlockModel(
                "r",
                "Reserve",
                "right",
                100,
                0,
                {"lambda": 0.001, "block_role": "k_of_n", "k_required": 2, "n_total": 3},
            ),
            BlockModel("end", "End", "out", 200, 0, {}),
        ],
        connections=[
            ConnectionModel("c1", "start", "out", "r", "left"),
            ConnectionModel("c2", "r", "right", "end", "in"),
        ],
    )

    result = FormulaGenerationService().generate(scheme, time_horizon=100)

    assert any(item.node_type == "sliding_reserve" for item in result.analysis)
    assert any(item.status == "manual_required" for item in result.selections)


def test_method_selector_marks_explicit_k_of_n_block_as_reserve():
    scheme = SchemeModel(
        name="ReserveLike",
        blocks=[
            BlockModel("start", "Start", "in", 0, 0, {}),
            BlockModel(
                "r",
                "Reserve",
                "right",
                100,
                0,
                {"lambda": 0.001, "block_role": "k_of_n", "k_required": 2, "n_total": 3},
            ),
            BlockModel("end", "End", "out", 200, 0, {}),
        ],
        connections=[
            ConnectionModel("c1", "start", "out", "r", "left"),
            ConnectionModel("c2", "r", "right", "end", "in"),
        ],
    )

    selection = select_method_for_scheme(scheme)

    assert selection.analysis.has_reserve


def test_dependability_graph_accepts_string_engineering_params_without_float_crash():
    graph = Graph()
    graph.add_node("B1", {"lambda": 0.001, "Tv": 10.0, "t": 1000, "block_role": "ordinary"})

    assert graph.blocks_data["B1"]["lambda"] == 0.001
    assert graph.blocks_data["B1"]["Tv"] == 10.0
    assert graph.blocks_data["B1"]["t"] == 1000.0
    assert graph.blocks_data["B1"]["block_role"] == "ordinary"


def test_block_props_dialog_source_uses_russian_close_button():
    root = Path(__file__).resolve().parents[1]
    source = (root / 'app' / 'gui' / 'gui_dialogs.py').read_text(encoding="utf-8")

    assert 'cancel_button.setText("Закрыть")' in source
