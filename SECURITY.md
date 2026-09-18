# Security Policy

## Reporting a vulnerability

Please use [GitHub private vulnerability reporting](https://github.com/Archolith/beacon/security/advisories/new).
Do not open a public issue for suspected vulnerabilities and do not include secrets or private
repository content in a report.

Include the affected version or commit, a minimal reproduction, impact, and any suggested
mitigation. You should receive an acknowledgement within seven days. We will coordinate disclosure
after a fix is available when the report is valid.

## Supported versions

Beacon has no supported public release yet. The `release/v0.2.0` line is under active development;
security fixes are accepted there until v0.2.0 is released. This section will become a concrete
version-support table with the first public release.

## Security boundary

Beacon v0.2 is designed to operate offline over bounded local files and stdio. Unexpected network
access, secret disclosure, path escape, unsafe overwrite, unbounded parsing, or publication of
unreviewed sensitive content should be treated as security-relevant behavior.
