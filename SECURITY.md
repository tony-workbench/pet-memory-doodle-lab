# Security scope

A single-user local prototype. The trust boundary is a browser on the same computer talking to a loopback-only Python process. Local programs running as the same user are trusted; the app is not a sandbox against a compromised computer.

## Hosted demo

A separate static-only build: the public prompt, interface, design notes and sample image. It has no image-generation server, API key, secret, user database or writable API, and deploying it does not expose the Python server.

The browser builds the prompt locally; editing text sends nothing to the provider or host. Ordinary hosting access logs are outside the app's control. The build script copies an explicit file list, so `.git`, Python sources, environment files, scan reports and private research are never packaged. Publishing never needs credentials in Git.

## Data flow

Scene and object text goes to the local server to build a prompt. Clicking Generate sends only that prompt plus fixed image options to the OpenAI Images API over HTTPS. The server reads `OPENAI_API_KEY` from its environment; responses carry the image, never the key. The app stores no edits or results; downloads stay where the user saves them. The provider's own data handling is out of scope.

There is no multi-user authentication or account-wide budget. Do not expose the app to a network or a public reverse proxy without a separate security design.

## Controls

- Loopback binding, strict Host and Origin checks, same-origin fetch policy, and a per-process CSRF token for POST requests.
- Fixed static-file allowlist; no directory browser, arbitrary file reads, upload route, or shell execution.
- Bounded JSON requests, typed and length-limited fields, generation concurrency control and cooldown.
- Fixed HTTPS image provider; redirects are rejected. Provider responses are bounded and accepted only as base64-encoded PNG images.
- User input rendered as text; relative same-site asset URLs.
- No credential field in the browser, no analytics, no third-party scripts, and no diary or provider-response logging.
- Content Security Policy, `nosniff`, no framing, restricted browser permissions, and no-store responses.

## Verification

`python3 -m unittest discover -s tests -v` uses a fake image provider (no cost, no key) and makes real HTTP requests to the loopback server. No real paid generation has been run from this app, and tests cannot rule out every vulnerability.
