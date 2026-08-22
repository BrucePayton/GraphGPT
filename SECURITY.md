# Security Policy

## Supported versions

Security fixes are provided for the latest minor release. Users should upgrade to the newest
`graphgpt-builder` version before reporting an issue.

## Report a vulnerability privately

Do not open a public issue for suspected vulnerabilities. Use
[GitHub private vulnerability reporting](https://github.com/BrucePayton/GraphGPT/security/advisories/new)
and include:

- affected GraphGPT and Python versions;
- a minimal reproduction or malformed workflow/plugin package;
- expected impact and any known workarounds;
- whether credentials or user code may have been exposed.

We aim to acknowledge reports within 3 business days, provide an initial assessment within 7 days,
and coordinate disclosure after a fix is available. Timelines may vary with severity and complexity.

## Security boundaries

GraphGPT treats workflow YAML, plugin entry points, Python bindings, environment references, and
observability callbacks as distinct trust boundaries. Validation must remain side-effect free and
must not import workflow code. Installing or compiling a third-party plugin executes code from that
package; only install plugins from publishers you trust.

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the implementation boundaries.
