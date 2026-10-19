# Security scope

This is a single-user local prototype. Its intended trust boundary is a browser on the same computer connecting to a loopback-only Python process. Local programs running as the same user are trusted; the application is not a sandbox against a compromised computer.

## Data flow

Scene and object descriptions are sent to the local server to build a prompt. Clicking Generate sends that prompt, and only that prompt plus fixed image options, to the OpenAI Images API over HTTPS. The server supplies `OPENAI_API_KEY` from its process environment. API responses contain a generated image, never the key. Browser edits and generated results are not persisted by this application. Downloaded files remain wherever the user saves them. The image provider's own data handling is outside this local implementation.

The app does not authenticate multiple users or enforce account-wide budgets. Do not expose it to a network or place it behind a public reverse proxy without a separate deployment security design.

## Controls

- Loopback binding, strict Host and Origin checks, same-origin fetch policy, and a per-process CSRF token for POST requests.
- Fixed static-file allowlist; no directory browser, arbitrary file reads, upload route, or shell execution.
- Bounded JSON requests, typed and length-limited fields, generation concurrency control and cooldown.
- Fixed HTTPS image provider; redirects are rejected. Provider responses are bounded and accepted only as base64-encoded PNG images.
- No credential field in the browser, no analytics, no third-party scripts, and no diary or provider-response logging.
- Content Security Policy, `nosniff`, no framing, restricted browser permissions, and no-store responses.

## Verification

Run `python3 -m unittest discover -s tests -v`. The tests use a fake provider; they do not consume credits or require a real credential.

Initial local verification passed 23 automated tests, including real loopback HTTP requests and simulated provider responses. The JavaScript syntax check passed. An explicit 11-file upload allowlist and common credential/private-path pattern check found no matches. That pattern check is bounded and is not an exhaustive secret detector.

A separate pre-upload source review covers credential exposure, local-file disclosure, cross-site requests, unsafe rendering, outbound destination control, and accidental inclusion of private research files. Its report is retained outside the repository so private workstation paths and scan metadata are not uploaded.

Static review and tests cannot guarantee the absence of every vulnerability. A real paid API generation has not been exercised in this standalone app because no API key was configured during its initial build.
