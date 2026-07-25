# Beacon Security and Visibility Model

**Date:** 2026-06-29  
**Status:** early security/design note  
**Scope:** what Beacon should expose, to whom, and under what trust model

## 0. Purpose

Beacon exposes project understanding to agents.

That understanding can include:

- architecture
- risky files
- guardrails
- implementation locations
- dependency structure
- decision history
- Git history
- project memory
- benchmark context
- temporal blast radius

This is useful to legitimate agents.

It can also be useful reconnaissance for a malicious or compromised agent.

Security and visibility must therefore become first-class Beacon design concerns.

## 1. Core risk

A Beacon that says:

> Here are the most sensitive files, why they are risky, and what architectural constraints protect them.

is helpful for safe coding.

It is also a map of where to attack.

This does not mean Beacon should avoid guardrails or structure. It means Beacon needs explicit visibility levels.

## 2. Visibility tiers

Beacon should eventually support multiple visibility tiers.

| Tier | Audience | Example content |
| --- | --- | --- |
| Public | anonymous users / public agents | overview, public docs, basic contribution guide |
| Authenticated | known users or approved agents | more detailed docs, task onboarding, non-sensitive guardrails |
| Organization | members of an org/team | internal architecture, private docs, richer file guidance |
| Maintainer | trusted maintainers / CI / internal agents | sensitive guardrails, risky files, decision history, blast radius |
| Local-only | local developer machine | full code structure, private memory, secrets-adjacent warnings |

The exact tiers may change, but the principle should remain:

> Not every Beacon capability should be exposed to every caller.

## 3. Capability visibility

Different capabilities carry different risk.

Low-risk public capabilities:

- project overview
- public onboarding
- public search over public docs
- contribution guide

Medium-risk capabilities:

- guardrails
- file discovery
- concept explanations tied to implementation
- recent change summaries

High-risk capabilities:

- risky file maps
- temporal blast radius
- internal decision history
- private project memory
- sensitive dependency structure
- security-related architecture notes

## 4. Public Beacon profile

A public Beacon should probably expose only:

- project overview
- public onboarding
- public canonical docs
- public contribution paths
- general guardrails
- public source citations

It should avoid exposing:

- private memories
- internal risk maps
- security-sensitive file lists
- detailed vulnerability history
- internal decision discussions
- private branches or commits

## 5. Authenticated Beacon profile

Authenticated Beacons can expose richer information, but should still classify outputs.

Possible rules:

- authenticated users see task-specific onboarding
- organization members see internal docs
- maintainers see risky files and blast-radius analysis
- CI sees strict validation and drift reports

## 6. Local Beacon profile

A local Beacon running on a developer machine may safely expose more, because the caller already has repository access.

Even then, tool outputs should avoid accidentally leaking secrets or private credentials into model context.

Local Beacon should still respect:

- `.gitignore`
- secret scanners
- denylisted paths
- generated files
- private memory scopes
- explicit visibility metadata

## 7. Guardrails for guardrails

Beacon guardrails need their own guardrails.

A guardrail can reveal sensitive information if written too explicitly.

Example risky guardrail:

```text
Do not edit src/auth/token_signing.py because it contains the production JWT signing flow.
```

Safer public guardrail:

```text
Authentication-sensitive code requires maintainer review.
```

Richer authenticated guardrail:

```text
Auth/token signing changes require maintainer review and security tests.
```

## 8. Source classification

Beacon sources should eventually support classification metadata.

Example:

```json
{
  "source": {
    "path": "docs/security/internal-auth.md",
    "visibility": "organization",
    "classification": "internal",
    "allowed_capabilities": ["guardrails", "agent_onboarding"]
  }
}
```

## 9. Provider responsibility

Providers should enforce visibility before returning data.

The transport should not be the only security boundary.

A provider should know:

- who is asking
- what capability is requested
- what sources are allowed
- what output fields are allowed
- whether the request is public/local/authenticated

## 10. Transport implications

MCP stdio is a good local transport.

For public or hosted Beacons, HTTP or remote MCP require stronger controls:

- authentication
- authorization
- logging
- rate limits
- audit trails
- source visibility filtering
- capability allowlists

## 11. Registry implications

If Beacon later has a registry or discovery service, it should not imply trust by default.

Registry entries may need:

- verified publisher identity
- signed manifests
- transport metadata
- public/private visibility flags
- supported capability list
- provider tier
- last verified timestamp

## 12. Design principle

Beacon should expose enough information for agents to work safely, but not so much that it becomes a reconnaissance endpoint.

Default stance:

> Public Beacon should be safe and useful. Rich Beacon should be authenticated or local.

## 13. Roadmap

Recommended security roadmap:

1. Add visibility field to sources and guardrails.
2. Add public/default output profile.
3. Add denylisted paths and ignored files.
4. Add provider-level capability allowlists.
5. Add local vs public mode distinction.
6. Add authentication for remote transports.
7. Add source classification and redaction.
8. Add audit logs for hosted Beacons.

Do not wait until Beacon is widely used to add visibility concepts. Retrofitting security later will be harder.
