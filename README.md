# Надёжность технических средств

Настольное приложение на Python и PyQt6 для построения структурных схем надежности, расчета показателей, генерации общей формулы системы и подготовки отчетных материалов. Проект предназначен как демонстрационный инженерный прототип: пользователь может собрать схему, задать параметры элементов, получить формулу, выполнить расчет, построить график и экспортировать результаты.

## Основные возможности

- Графический редактор структурных схем надежности на `QGraphicsScene/QGraphicsView`.
- Полноценные связи между блоками: линии привязаны к объектам, обновляются при перемещении и сохраняются в модели схемы.
- Встроенные шаблоны: последовательная схема, параллельная схема, комбинированная схема и резервирование 1+1.
- Сохранение и загрузка схем в JSON.
- Экспорт изображения схемы в SVG и PNG.
- Генератор общей формулы по схеме для `Pсист(t)` и `Kг_сист`.
- Интеллектуальный слой выбора формул: схема анализируется, типовые фрагменты сопоставляются с библиотекой проектных формул, параметры подставляются в объяснение.
- Анализ схемы и подбор подходящего сценария/метода расчета.
- Калькулятор методов F1.1-F7.2 с параметрами, графиком и описанием методики.
- Экспорт отчетов и таблиц в HTML, TXT, DOCX, PDF и XLSX.
- Выбор пути сохранения через стандартные файловые диалоги.
- Документация, тесты, встроенная самопроверка генератора формул.

## Быстрый старт

### Разработка из исходников на Windows

1. Установите Python `3.13.x` для Windows.
2. Откройте папку проекта.
3. Запустите bootstrap-скрипт:

```powershell
.\run_app.ps1
```

Скрипт сам:

- проверит локальную `.venv`;
- пересоздаст её, если она была перенесена с другого ПК или повреждена;
- установит зависимости из `requirements.txt`;
- запустит `main.py`.

Если PowerShell неудобен, используйте:

```bash
run_app.bat
```

Важно: `.venv` не должна переноситься между компьютерами. Это локальное окружение конкретного ПК. При переносе проекта копируйте исходники, а окружение создавайте заново через `run_app.ps1`.

Перед изменением существующих файлов в проекте теперь обязательно создаются backup-копии. Порядок описан в [docs/BACKUP_AND_RESTORE.md](docs/BACKUP_AND_RESTORE.md).

### Запуск через VS Code

- Откройте проект в VS Code.
- Первый запуск можно сделать сразу через `Play` у `main.py`: перед стартом автоматически выполнится bootstrap-задача.
- После этого VS Code будет использовать локальную `${workspaceFolder}\.venv\Scripts\python.exe`.

### Готовый exe

Если на компьютере не установлен Python и код менять не нужно, используйте готовую сборку:

```text
dist\ReliabilityApp.exe
```

## Быстрая проверка работы

1. Запустите `.\run_app.ps1` или `Play` в VS Code.
2. Откройте модуль `Графический редактор`.
3. В левой панели выберите шаблон, например `Последовательная схема`, и нажмите `Применить шаблон`.
4. Нажмите `Сгенерировать формулу`.
5. Проверьте, что показана формула вида `Pсист(t) = B1 · B2` и `Kг_сист = K_B1 · K_B2`.
6. Нажмите `Рассчитать схему`.
7. Нажмите `Проверить систему`, чтобы выполнить встроенную самопроверку генератора формул.

## Project structure

The application code is now organized under the `app/` package. The detailed folder map is documented in [docs/PROJECT_STRUCTURE.md](docs/PROJECT_STRUCTURE.md).

Key areas:

- `app/main.py` ? primary entrypoint for `python -m app.main`.
- `main.py` ? compatibility wrapper for launching from the project root.
- `gui_main.py` ? small compatibility wrapper for the old launch command.
- `app/gui/` ? GUI files: main window, calculator, visual editor, dialogs, styles and help content.
- `app/core/` ? models, calculation core, validators, normative methods, method selection and contribution analysis.
- `app/formulas/` ? formula generation, packaging and rendering.
- `app/reports/` ? HTML/TXT/PDF/DOCX/XLSX report export.
- `app/import_export/` ? JSON/YAML import/export, scheme storage and scene image export.
- `app/demo/` ? demo scenarios, built-in templates and `db_modules.json`.
- `app/utils/` ? constants, logging and robust project path helpers.
- `examples/`, `docs/`, `resources/`, `tests/`, `tools/` ? examples, docs, resources, tests and helper scripts.

Main launch commands:

```bash
python -m app.main
python main.py
```

On Windows, `run_app.ps1` and `run_app.bat` remain available.

## Документация

- [Backup и восстановление](docs/BACKUP_AND_RESTORE.md)
- [Руководство пользователя](docs/USER_GUIDE.md)
- [Справочник интерфейса](docs/UI_REFERENCE.md)
- [Формулы и методики](docs/FORMULAS_AND_METHODS.md)
- [Архитектура](docs/ARCHITECTURE.md)
- [Справочник файлов и модулей](docs/MODULE_REFERENCE.md)
- [Руководство разработчика](docs/DEVELOPER_GUIDE.md)
- [Тестирование](docs/TESTING.md)
- [Типовые проблемы и ограничения](docs/TROUBLESHOOTING.md)
- [Финальная готовность к сдаче](docs/FINAL_READINESS.md)

## Тесты

```bash
pytest
```

Основные проверки покрывают:

- расчетное ядро;
- генератор формул для последовательных, параллельных, вложенных и резервированных схем;
- согласованность AST, формулы, обозначений и объяснений;
- выбор сценария и метода;
- сохранение/загрузку схем;
- экспорт HTML, DOCX и XLSX.

## Supported formats

- Input schemes: JSON and YAML examples from `examples/`.
- Report export: HTML, TXT, PDF, DOCX and XLSX.
- Scheme image export: PNG and SVG.
- Demo data: `app/demo/db_modules.json` and built-in Python templates.

## Ограничения текущей версии

- Генератор формул рассчитан на ациклические структурные схемы с одним входом и одним выходом.
- Для очень сложных непоследовательно-параллельных графов формула может быть построена как композиционная приближенная интерпретация или сопровождаться предупреждением.
- Вложенные схемы реализованы как рабочий MVP: блок может хранить внутреннюю `SchemeModel`, которая учитывается в формуле и сериализации.
- DOCX экспорт использует `python-docx`, XLSX экспорт использует `openpyxl`, PDF экспорт использует Qt-печать. Это пригодно для демонстрации и передачи преподавателю, но не заменяет промышленный офисный генератор.

## Сборка в exe

Файл `ReliabilityApp.spec` подготовлен как основа для PyInstaller. Иконка приложения находится в `resources/app_icon.ico` и подключается к окну и будущей сборке.
