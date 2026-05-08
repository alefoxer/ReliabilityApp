from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from app.core.rbd_models import BlockModel, ConnectionModel, SchemeModel


def built_in_templates() -> list[SchemeModel]:
    return [
        SchemeModel(
            name="Последовательная схема",
            blocks=[
                BlockModel("start", "Вход", "in", 40, 120, {}),
                BlockModel("b1", "Блок 1", "right", 180, 120, {"lambda": 0.001, "Tv": 10.0, "t": 1000}),
                BlockModel("b2", "Блок 2", "right", 340, 120, {"lambda": 0.0015, "Tv": 10.0, "t": 1000}),
                BlockModel("end", "Выход", "out", 520, 120, {}),
            ],
            connections=[
                ConnectionModel("c1", "start", "out", "b1", "left"),
                ConnectionModel("c2", "b1", "right", "b2", "left"),
                ConnectionModel("c3", "b2", "right", "end", "in"),
            ],
        ),
        SchemeModel(
            name="Параллельная схема",
            blocks=[
                BlockModel("start", "Вход", "in", 40, 180, {}),
                BlockModel("split", "Разветвление", "junction", 180, 180, {}),
                BlockModel("top", "Верхняя ветвь", "right", 340, 100, {"lambda": 0.001, "Tv": 10.0, "t": 1000}),
                BlockModel("bottom", "Нижняя ветвь", "right", 340, 260, {"lambda": 0.0012, "Tv": 10.0, "t": 1000}),
                BlockModel("join", "Слияние", "junction", 500, 180, {}),
                BlockModel("end", "Выход", "out", 700, 180, {}),
            ],
            connections=[
                ConnectionModel("c1", "start", "out", "split", "left"),
                ConnectionModel("c2", "split", "right", "top", "left"),
                ConnectionModel("c3", "split", "down_spec", "bottom", "left"),
                ConnectionModel("c4", "top", "right", "join", "left"),
                ConnectionModel("c5", "bottom", "right", "join", "up_spec"),
                ConnectionModel("c6", "join", "right", "end", "in"),
            ],
        ),
        SchemeModel(
            name="Смешанная схема",
            blocks=[
                BlockModel("start", "Вход", "in", 40, 180, {}),
                BlockModel("a", "Блок 1", "right", 180, 180, {"lambda": 0.001, "Tv": 8.0, "t": 1000}),
                BlockModel("split", "Разветвление", "junction", 330, 180, {}),
                BlockModel("b", "Блок 2", "right", 500, 105, {"lambda": 0.0012, "Tv": 10.0, "t": 1000}),
                BlockModel("c", "Блок 3", "right", 500, 255, {"lambda": 0.0008, "Tv": 12.0, "t": 1000}),
                BlockModel("join", "Слияние", "junction", 660, 180, {}),
                BlockModel("d", "Блок 4", "right", 820, 180, {"lambda": 0.001, "Tv": 9.0, "t": 1000}),
                BlockModel("end", "Выход", "out", 980, 180, {}),
            ],
            connections=[
                ConnectionModel("c1", "start", "out", "a", "left"),
                ConnectionModel("c2", "a", "right", "split", "left"),
                ConnectionModel("c3", "split", "right", "b", "left"),
                ConnectionModel("c4", "split", "down_spec", "c", "left"),
                ConnectionModel("c5", "b", "right", "join", "left"),
                ConnectionModel("c6", "c", "right", "join", "up_spec"),
                ConnectionModel("c7", "join", "right", "d", "left"),
                ConnectionModel("c8", "d", "right", "end", "in"),
            ],
        ),
        SchemeModel(
            name="Схема с резервированием",
            blocks=[
                BlockModel("start", "Вход", "in", 40, 140, {}),
                BlockModel("reserve", "Блок с резервом", "right", 220, 140, {"lambda": 0.001, "Tv": 10.0, "t": 1000, "reserve_count": 1}),
                BlockModel("end", "Выход", "out", 520, 140, {}),
            ],
            connections=[
                ConnectionModel("c1", "start", "out", "reserve", "left"),
                ConnectionModel("c2", "reserve", "right", "end", "in"),
            ],
        ),
    ]


def save_user_templates(path: str | Path, templates: list[SchemeModel]) -> None:
    target = Path(path)
    payload = [asdict(template) for template in templates]
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_user_templates(path: str | Path) -> list[SchemeModel]:
    target = Path(path)
    if not target.exists():
        return []
    raw = json.loads(target.read_text(encoding="utf-8"))
    templates: list[SchemeModel] = []
    for item in raw:
        blocks = [BlockModel(**block) for block in item.get("blocks", [])]
        connections = [
            ConnectionModel(
                connection_id=connection.get("connection_id", ""),
                source_id=connection["source_id"],
                source_port=connection["source_port"],
                target_id=connection["target_id"],
                target_port=connection["target_port"],
            )
            for connection in item.get("connections", [])
        ]
        templates.append(SchemeModel(name=item.get("name", "Шаблон"), blocks=blocks, connections=connections))
    return templates
