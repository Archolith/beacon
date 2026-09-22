# Beacon v0.2 unaided developer trial scorecard

## Trial boundary

- Participant did not write the Beacon v0.2 implementation: `<yes/no>`
- Participant has not received a Beacon setup walkthrough: `<yes/no>`
- Environment is a fresh machine/account or clean virtual environment: `<describe>`
- Beacon source checkout or editable install is absent: `<yes/no>`
- Python version and operating system: `<value>`
- MCP client used: `<value>`
- Participant repository: `<name or private description>`
- Observer: `<name>`
- Date: `<ISO date>`

Give the participant only this brief before starting the clock:

> Using only Beacon's public package and public repository documentation, install the `0.2.0rc2` release candidate and set it up for a small repository you understand. Produce and review its manifest, validate it, inspect its project context for a real task, export a snapshot, and connect Beacon to an MCP client. Stop after 15 minutes or at the first blocking step.

The observer may answer process questions only after the clock stops. Any help needed during the
clock is recorded as undocumented maintainer knowledge and fails this trial.

## Timed observations

| Milestone | Elapsed time | Result | Notes |
| --- | ---: | --- | --- |
| Public-index install completes | | `<pass/fail>` | |
| Generated manifest is available for review | | `<pass/fail>` | |
| Validation errors/warnings are resolved | | `<pass/fail>` | |
| Participant can explain the inspect output | | `<pass/fail>` | |
| Snapshot export completes | | `<pass/fail>` | |
| MCP client connects and lists exactly five Beacon tools | | `<pass/fail>` | |
| All five tools return a response | | `<pass/fail>` | |
| Participant identifies expected docs/files/commands/guardrails for one real task | | `<pass/fail>` | |

## Product checks

- Install source and exact versions observed: `<value>`
- Validation diagnostics encountered and resolution: `<value>`
- Every cited path resolves: `<yes/no; details>`
- Unsupported high-confidence claim found in output: `<none/details>`
- Repeated export is byte-identical with unchanged inputs: `<yes/no>`
- Init refused unsafe overwrite/path conditions when encountered: `<not encountered/pass/fail>`
- Undocumented maintainer knowledge required: `<none/details>`
- First blocking step, if any: `<none/details>`
- Participant's one-sentence product explanation: `<value>`

## Result

- Total elapsed time: `<mm:ss>`
- Completed local setup within 15 minutes: `<yes/no>`
- Zero undocumented blocking steps: `<yes/no>`
- Zero unsupported high-confidence claims: `<yes/no>`
- All citations resolve: `<yes/no>`
- All five tools respond: `<yes/no>`
- Wheel, not editable checkout, completed the journey: `<yes/no>`
- Overall result: `<PASS/FAIL>`

Any failed exit target is a blocking v0.2 remediation item. Record the fix separately and run a
new unaided trial with an eligible participant; do not coach the original run into a pass.
