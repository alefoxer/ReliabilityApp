# Importing Reliability Schemes From External Sources

## Current State

The editor's native project format is the existing `SchemeModel` JSON saved by `scheme_storage.py`.
It stores graph blocks, connections, numeric block parameters, nested subschemes and scheme metadata.
Previously the application could load only this own JSON format; DOC/DOCX/PDF/XLSX were not reliable
calculation inputs and were not converted into a calculation model.

The formula generator already works from the internal graph structure, not from a picture. The new import
layer keeps that rule: external documents are sources of data, while calculation is performed only after
normalization into a structured project.

## Format Strategy

The supported pipeline is:

`external document -> extracted/reviewed data -> ImportedReliabilityProject JSON/YAML -> SchemeModel -> formula library -> calculation/report`.

Supported import levels:

- Reliable structured import: JSON is mandatory; YAML is supported through the project dependency `PyYAML`.
- Semi-automatic document import: DOC/DOCX/PDF/XLSX should be treated as extraction sources for text,
  tables and formulas, then reviewed and saved as JSON/YAML.
- Manual review: damaged formulas, ambiguous tables and figure-only schemes must be marked for review.
- Illustrations: images from documents may be kept for reports, but are not accepted as calculation
  semantics unless blocks and connections are explicitly normalized.

## ImportedReliabilityProject

Top-level fields:

- `schema_version`: format version, currently `1.0`.
- `project_name`: project title.
- `source`: document/source metadata and confidence.
- `requirements`: thresholds such as `P_min`, `K_min`, restore-time limits.
- `calculation_conditions`: time values, operating mode, temperature and assumptions.
- `components`: reusable elements with quantities and parameters.
- `schemes`: normalized schemes with `series`, `parallel`, `reserve_group`, `element`, and `nested_scheme` nodes.
- `formulas`: source formulas and their verification status.
- `expected_results`: reference values for comparison.
- `warnings`: import limitations shown to the user.
- `manual_review_required`: items that must not be treated as verified.

Example files:

- `examples/imported/sne_emrtu_project.json` - reference SNE EMRTU normalized project.
- `examples/imported/simple_series_project.yaml` - compact YAML example for a two-element series scheme.
- UI button `Демо СНЭ` loads the SNE example, converts scheme `sne_top` into the editor graph,
  runs calculation for `t = 158 h`, and shows comparison with imported reference values.

## Formula Verification Status

Formula definitions now expose:

- `project_method`: implemented project method, not an external normative claim.
- `needs_review`: extracted or placeholder formula that requires manual verification.
- `manual_required`: no safe automatic calculation method is available.
- `gost_based`: reserved for formulas with an exact verified standard reference.
- `verified`: reserved for formulas verified against the declared source.

The generator may use project methods for structural composition, but it must not label them as GOST.
For unsupported k-of-N sliding loaded reserve, the import layer records `k_required` and `n_total`, adds a
manual-review warning, and does not silently replace it with simple `reserve_count`.

Detailed status rules are described in `docs/FORMULA_VERIFICATION_STATUS.md`.

## Reference SNE Example

The SNE EMRTU document is used as an engineering reference dataset, not as a hard-coded parser template.
The normalized example contains:

- Top-level SNE series scheme with six components from the reference result tables.
- Per-time probabilities for `t = 158 h` and `t = 125 h`.
- Availability values from the reference table.
- A repeated-chain example for `N = 154`.
- A reserve-group placeholder for `175 of 204`, marked `needs_review`.
- Expected results for comparison.

Known limitations:

- Figure recognition is not considered reliable semantic import.
- Some PDF/DOC formula text can be damaged by conversion.
- The reference document contains apparent inconsistencies between table products and conclusion text;
  the normalized example uses table values and records the inconsistency as a warning.
