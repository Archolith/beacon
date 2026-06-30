# Beacon Positioning: Project Introspection Protocol

**Status:** Positioning note

## Core thesis

Beacon should not primarily be described as a structured README or documentation surface.

Beacon is a **project introspection protocol**.

Just as the Language Server Protocol (LSP) standardized editor-to-language communication, Beacon aims to standardize agent-to-project communication.

## Before and after

Before LSP:

Editor × Language = bespoke integrations.

After LSP:

Editors speak one protocol. Languages implement one server.

Before Beacon:

Agents repeatedly discover project structure using grep, glob, read-file and search tools.

After Beacon:

Agents ask the project directly through a standard capability contract.

## The shift

Documentation answers 'what should I read?'.

Beacon should answer:

- What modules exist?
- What symbols are exported?
- What depends on this function?
- What recently changed?
- What guardrails apply?
- What is the blast radius?

These are infrastructure questions, not documentation questions.

## Strategic implication

Beacon should compete less with AGENTS.md or CLAUDE.md and more with the absence of any standard project introspection layer.

The long-term vision is that any agent can connect to any project through the same interface regardless of implementation.

Example:

beacon://menhir
beacon://postgres
beacon://fastapi

The provider may differ, but the capability contract remains stable.