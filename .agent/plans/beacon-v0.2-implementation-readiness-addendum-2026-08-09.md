# Beacon v0.2 — Implementation Readiness Addendum

**Status:** READY FOR IMPLEMENTATION
**Date:** 2026-08-09
**Owner:** Beacon
**Parent plan:** `.agent/plans/beacon-v0.2-publishable-static-product-plan-2026-08-09.md`
**Target release:** `0.2.0`

## 1. Purpose

This addendum closes the implementation-level decisions left after the v0.2 product plan. It is
normative for v0.2 where it is more specific than the parent plan.

Executable machine contracts:

- `docs/schemas/beacon-cli-result-1.0.schema.json`
- `docs/schemas/beacon-init-report-1.0.schema.json`
- `docs/schemas/beacon-snapshot-1.0.schema.json`

Implementation changes to these contracts require fixture updates and explicit plan review. Prose
examples alone do not change a machine contract.

## 2. Approved readiness decisions

1. **MCP baseline:** v0.2 remains on stable FastMCP 3.x and stdio. FastMCP 4 and stateless MCP
   `2026-07-28` migration wait until FastMCP 4 is stable and the Archolith framework migrates.
2. **Repository scale:** v0.2 supports small-to-medium repositories through conservative defaults
   with explicit overrides. Large-monorepo support requires later benchmark evidence.
3. **Intentional absence:** projects may publish without automated tests or guardrails only when
   each absence is explicitly acknowledged with a reason.
4. **Secret safety:** high-confidence secret findings block `init`/`export` unless an explicit,
   reasoned override is recorded without echoing the secret.
5. **Privacy:** v0.2 performs no telemetry, analytics, update checks, or outbound runtime network
   access. Manifest commands are inert data and are never executed.
6. **Release order:** publish `archolith-mcp-framework==0.2.0`, then
   `archolith-beacon==0.2.0rc1`, then `archolith-beacon==0.2.0`, with TestPyPI smoke before each
   applicable real-index release.
7. **PyPI access:** Archolith account/organization and two-maintainer access are believed to exist
   but remain an explicit WP0 verification gate. No release relies on an assumption about access.

## 3. MCP and dependency compatibility

### v0.2 contract

- runtime framework: `archolith-mcp-framework>=0.2,<0.3`;
- framework import: `archolith_mcp_framework`;
- FastMCP: stable `>=3.2.4,<4` as constrained by the framework;
- transport: stdio only as the supported release transport;
- existing no-argument `beacon` stdio behavior remains compatible;
- five tool names, input shapes, answer dataclasses, and provider protocol remain frozen; and
- v0.2 does not claim support for MCP `2026-07-28` or the FastMCP 4 extension model.

### Required evidence

Before release:

1. Record the actual MCP protocol version(s) negotiated by the installed FastMCP 3 stack.
2. Run a black-box stdio test through the packaged console command, not only direct Python calls.
3. Run the documented setup against each supported MCP client fixture.
4. Verify that stdout contains only MCP frames and stderr carries logs.
5. Record the framework and FastMCP versions in release diagnostics.

FastMCP 4 migration is a separate compatibility project. It must test old and current protocol-era
clients before Beacon changes its stated support.

## 4. Resource limits

### Standard defaults

| Limit | Default | Applies to |
| --- | ---: | --- |
| Manifest source bytes | 1 MiB | load, validate, inspect, export, serve |
| YAML nesting depth | 32 | manifest parsing |
| YAML parsed nodes | 50,000 | manifest parsing |
| YAML aliases | 50 | manifest parsing |
| Canonical documents | 256 | inspect, export, serve |
| One canonical document | 2 MiB | indexing/export |
| Total canonical source bytes | 20 MiB | indexing/export |
| Total heading chunks | 10,000 | indexing/export/search |
| One relative path | 1,024 UTF-8 bytes | manifest/init/export |
| Query text | 4 KiB | search and task hints |
| Search result limit | 100 | provider/tool calls |
| Snapshot output | 50 MiB | export |
| Initialization report | 5 MiB | init report/stdout |

`MiB` means 1,048,576 bytes. Byte limits are checked before decoding or parsing. Integer arithmetic
must reject overflow and negative configuration values.

### Overrides

Each limit has one explicit CLI option and matching environment setting. CLI overrides environment;
environment overrides defaults. Suggested naming follows:

```text
--max-manifest-bytes       / BEACON_MAX_MANIFEST_BYTES
--max-documents            / BEACON_MAX_DOCUMENTS
--max-document-bytes       / BEACON_MAX_DOCUMENT_BYTES
--max-total-document-bytes / BEACON_MAX_TOTAL_DOCUMENT_BYTES
--max-chunks               / BEACON_MAX_CHUNKS
--max-snapshot-bytes       / BEACON_MAX_SNAPSHOT_BYTES
```

Parser depth/node/alias and path/query/result ceilings remain non-overridable safety limits in
v0.2. Server startup logs effective non-secret limits to stderr. CLI JSON results report effective
limits in command-specific `result` data where relevant.

An override does not establish large-repository support. Release notes describe only the standard
profile until a larger profile passes memory, time, and output-size benchmarks.

### Failure behavior

- limit checks happen before expensive work;
- exit code is `2` for user-configured/input safety refusal;
- stable diagnostic codes identify the exact limit;
- partial init/export artifacts are removed;
- diagnostics never include full document content; and
- no command silently truncates a canonical document or snapshot.

## 5. Validation and publication policy

### Servable versus publishable

```text
beacon validate
  errors block
  warnings are reported
  exit 0 when no errors

beacon validate --strict-warnings
  errors block
  unresolved publication warnings block
  explicitly permitted acknowledgements may resolve only allowlisted warnings

beacon serve
  errors block startup
  warnings are emitted and remain visible in diagnostics

beacon export
  errors and unresolved publication warnings block
  accepted acknowledgements are recorded in snapshot metadata
```

### Publication warnings

The validator must add stable codes, including:

| Code | Condition | Acknowledgeable in v0.2 |
| --- | --- | --- |
| `project_status_unknown` | `project.status` is `unknown` | No |
| `purpose_missing` | `purpose.one_sentence` is empty | No |
| `test_command_missing` | no automated test command is declared | Yes |
| `guardrails_missing` | no guardrail is declared | Yes |
| `concept_definition_missing` | concept has no definition | No |
| `related_concept_unknown` | related concept ID does not resolve | No |
| `knowledge_status_invalid` | status is outside controlled vocabulary | No |
| `canonical_doc_duplicate` | duplicate canonical path | No |

Existing error conditions retain error severity. Setup and benchmark commands are optional and do
not warn by themselves.

### Explicit acknowledgement

Text-mode commands accept a repeatable option:

```text
--acknowledge CODE=REASON
```

Rules:

- only `test_command_missing` and `guardrails_missing` are acknowledgeable in v0.2;
- reason is trimmed, non-empty, and at least 10 characters;
- unknown, duplicate, malformed, or unallowlisted codes cause exit `2`;
- acknowledgement changes policy disposition, not the underlying diagnostic severity or facts;
- text and JSON output label the diagnostic as acknowledged and preserve the reason;
- export records code and reason in `validation.acknowledgements`; and
- acknowledgements do not modify `beacon.yaml` or pretend a capability exists.

CI must include acknowledgements explicitly in its command or wrapper configuration. Comments and
empty strings are not acknowledgement mechanisms.

## 6. High-confidence secret policy

### Blocking findings

v0.2 blocks only high-confidence classes with bounded, deterministic detectors:

- PEM/OpenSSH private-key material;
- credential-bearing URLs with non-placeholder userinfo;
- supported provider token formats with strong fixed prefixes/check structure; and
- known sensitive files proposed by discovery, including `.env`, private key, credential, and
  netrc-style files.

Generic entropy guesses and broad words such as `password` do not block by themselves. This feature
is a safety backstop, not a replacement for a dedicated secret scanner.

Stable codes begin with:

```text
sensitive_private_key
sensitive_credential_url
sensitive_known_token
sensitive_file_excluded
```

### Detection behavior

- `init` never proposes known sensitive files as canonical documents;
- embedded `export` scans selected manifest/doc text before writing;
- metadata-only export still scans manifest values and paths but does not read doc bodies beyond
  bytes required for hashing/path validation;
- findings report code, relative path, and line when safe, but never the matched value;
- finding values and surrounding text are not logged; and
- detection is deterministic and offline.

### Explicit sensitive override

An exceptional export accepts a repeatable option:

```text
--allow-sensitive CODE=REASON
```

The same reason and validation rules as acknowledgements apply. The override is recorded in
`validation.security_overrides` and visible in human output. It never applies to credential-bearing
git remotes discovered during init, path escapes, private-key files selected by discovery, or
Beacon's own process environment.

## 7. Privacy and network promise

For every v0.2 runtime command after installation:

- no telemetry or usage analytics;
- no update/version checks;
- no remote schema fetches;
- no HTTP, DNS, git fetch, registry, or external-service calls;
- no runtime LLM, embeddings, or hosted inference;
- no execution of manifest setup/test/benchmark commands; and
- no document bodies in ordinary logs.

Reading local git configuration to discover a sanitized remote URL is allowed; invoking networked
git operations is not.

Tests deny outbound socket creation for init/validate/inspect/export/serve startup paths. Any
optional dependency telemetry is disabled or excluded. Release documentation distinguishes package
installation network access from Beacon runtime behavior.

## 8. Executable JSON contracts

### CLI envelope

`docs/schemas/beacon-cli-result-1.0.schema.json` owns the common envelope and diagnostic shape.
Command-specific `result` schemas may narrow it, but may not change envelope fields.

Human output is not a machine contract. JSON mode emits one UTF-8 document plus a final newline.
Expected outcomes do not mix human prose into stdout.

### Initialization report

`docs/schemas/beacon-init-report-1.0.schema.json` owns persisted/dry-run report shape. Paths are
repository-relative and forward-slash normalized. Evidence records describe bounded observations;
they do not embed source documents or environment values.

### Snapshot

`docs/schemas/beacon-snapshot-1.0.schema.json` owns the static snapshot shape. Runtime checks enforce
byte, path, aggregate chunk, canonicalization, and content-mode constraints that JSON Schema cannot
fully express.

The schema requires:

- separate product/generator, manifest, and snapshot versions;
- exact source digests;
- explicit embedded or metadata-only content mode;
- canonical manifest data;
- relative document paths and source line ranges;
- validation acknowledgements and sensitive overrides; and
- no timestamp or host identity in canonical snapshot content.

## 9. Release and supply-chain sequence

### Access preflight

Before any upload, verify rather than assume:

- Archolith controls both PyPI project namespaces or can register them;
- at least two maintainers have recoverable access to each distribution;
- GitHub Trusted Publishing is configured against the exact repository/workflow/environment;
- recovery contacts and account MFA are current; and
- licenses and repository URLs are present in both package metadata sets.

Current status is `believed available — unverified` until this checklist is recorded.

### Publication order

1. Build, inspect, and TestPyPI-smoke `archolith-mcp-framework==0.2.0`.
2. Publish framework `0.2.0` to real PyPI through Trusted Publishing.
3. Install framework `0.2.0` from real PyPI in a clean environment.
4. Build, inspect, and TestPyPI-smoke `archolith-beacon==0.2.0rc1` while resolving the framework
   from real PyPI.
5. Publish Beacon `0.2.0rc1` to real PyPI and run the full clean-install maintainer journey.
6. Fix any release-candidate defect in a later RC; never replace an uploaded artifact.
7. Build final Beacon `0.2.0` from the approved commit, verify artifact hashes, publish through the
   tag-triggered workflow, and rerun installed-wheel smoke tests.

No production dependency uses TestPyPI or a direct Git URL. Build artifacts are promoted by exact
digest or rebuilt through a documented reproducible process; they are not hand-edited between
checks.

## 10. Implementation merge order

1. WP0 dependency/package migration and protocol-version diagnostic test.
2. Shared limits model and bounded manifest/document readers.
3. Stable diagnostic codes and strict/acknowledgement policy.
4. CLI envelope schema implementation and golden fixtures.
5. Init report schema implementation, secret exclusions, and atomic scaffold.
6. Snapshot schema implementation, content modes, secret gate, and canonical writer.
7. Socket-deny privacy tests and black-box stdio MCP smoke.
8. CI/package/release-candidate workflows and cold-start scorecard.

Each merge unit must keep existing v0.1 manifests and all five tools green.

## 11. Final readiness gate

Implementation is release-ready only when:

- all three schemas pass Draft 2020-12 meta-validation;
- every schema has success and negative golden fixtures;
- standard limits fail before excessive allocation and leave no partial output;
- strict validation distinguishes unresolved and explicitly acknowledged absence;
- high-confidence secret fixtures block without leaking matched text;
- socket-deny tests prove runtime offline behavior;
- packaged stdio reports the tested MCP/framework versions and serves five tools;
- framework and Beacon install from public indexes in clean environments; and
- the 15-minute maintainer trial passes from the wheel.
