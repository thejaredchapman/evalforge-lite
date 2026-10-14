# Changelog

All notable changes to EvalForge Lite are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

## [1.1.0] - 2026-10-14

### Added
- **Compare one model across platforms.** A new dropdown on the front screen selects the same model on
  OpenRouter, Amazon Bedrock, Google Vertex AI and Microsoft Foundry in one click. It replaces the current
  selection and respects the 4-target cap.
- `data/comparisons.json`: a curated list of 12 cross-platform comparisons, loaded by
  `config.load_comparisons()` and resolved by `catalog.comparison_entries()`. Invalid entries are dropped with
  a logged warning, and a missing file just hides the dropdown. It ships in the PyPI package.
- `/api/catalog` now returns a `comparisons` key.
- `PickerCore.targetsForComparison()`, a DOM-free helper with tests.
- A test that fails if `comparisons.json` drifts from `providers.json`.
- Docs: "Comparing one model across platforms" in `docs/comparing-models.md`, and a plain-English explanation
  of the judge versus the policy gate.

### Fixed
- The comparison dropdown no longer shares the `provider-dropdown` class, which made selection syncing and tag
  filtering throw a TypeError after a comparison was clicked.

### Changed
- User guide and README now name all four providers.

## [1.0.1] - 2026-10-01

### Added
- User guide site (`docs/`) and a user-facing README.

## [1.0.0]

### Added
- Initial release: web app and MCP server comparing text LLMs across OpenRouter, Amazon Bedrock, Google Vertex AI
  and Microsoft Foundry, with judge and rule-check scoring, per-response evaluation, a company-policy gate,
  PDF and CSV reports, optional server-held keys, and PyPI, MCP registry and Claude plugin packaging.

[1.1.0]: https://github.com/thejaredchapman/evalforge-lite/compare/v1.0.1...v1.1.0
[1.0.1]: https://github.com/thejaredchapman/evalforge-lite/releases/tag/v1.0.1
