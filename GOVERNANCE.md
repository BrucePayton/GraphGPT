# Governance

GraphGPT uses a maintainer-led, consensus-seeking model.

## Roles

- **Contributors** submit issues, documentation, plugins, tests, and code.
- **Reviewers** have demonstrated sustained project knowledge and help assess changes.
- **Maintainers** merge changes, manage releases, handle security reports, and protect compatibility.

Roles are earned through consistent, constructive participation. Maintainers are responsible for
declaring conflicts of interest and may recuse themselves from decisions.

## Decisions

Routine changes are decided through pull-request review. Changes to the DSL, serialized IR, Python
public API, CLI contracts, plugin protocol, security model, or supported runtime range begin as an
RFC issue describing motivation, alternatives, migration, and compatibility. Maintainers seek rough
consensus; when consensus is not possible, they document the final decision and rationale.

## Releases and compatibility

GraphGPT follows SemVer for its Python distribution. DSL and plugin API versions evolve separately.
Deprecations should remain available for at least one minor release during 0.x development and must
include a migration path. Security releases may shorten that window.

## Amendments

Governance changes use the same RFC process and require approval from active maintainers.
