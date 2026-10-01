# Browser libraries are vendored, not loaded from a CDN

Chart.js, marked, DOMPurify and highlight.js are committed minified under `ctokens/web/static/vendor/` (~380 KB,
with their licenses) and served by the tool itself, instead of being loaded from cdnjs with SRI as first designed.
This lets the UI work without internet or behind a network that blocks CDNs, removes the SRI hashes that would
need updating by hand, and lets the CSP allow only `'self'`. The cost is third-party files in the repo, refreshed
with `tools/vendor.py` when a version is bumped.
