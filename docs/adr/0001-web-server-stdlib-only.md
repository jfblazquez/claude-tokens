# Web server built on the standard library only

The web mode (JSON API + UI) uses only the Python standard library (`http.server`, `json`) and static HTML/CSS/JS
with no build step, instead of FastAPI/Flask. The tool is a dependency-free single script, and the server only
listens on localhost for one user with mostly read-only traffic, so a framework's validation, OpenAPI and async
features don't pay for the install step. Browser-side libraries are allowed; nothing is installed on the Python
side. (How they are delivered: [ADR 0002](0002-vendored-browser-libraries.md).)
