# Partial search failure proof

A search combines station-name, country, and tag requests. Previously, a failed
request became an empty list. If either remaining request succeeded, the helper
published incomplete results and the UI removed cached matches without an error.
Now all three requests must complete before results are published. A failed
request leaves runtime results untouched and the UI keeps its cached preview
with the existing service-unavailable message.

[evidence.json](evidence.json) compares the helper from main commit
`7f2d119cf6b9d351983b538e266f0637f3ccadec` with the fixed helper:

| Query | Failed request | Cached matches | Before | After |
| --- | --- | ---: | --- | --- |
| `jazz` | Tag | 1 | Empty results, no warning | Cached match retained, warning shown |
| `USA` | Country code | 3 | 2 partial results, no warning | All cached matches retained, warning shown |
| `jazz` | Station name | 2 | 1 partial result, no warning | All cached matches retained, warning shown |

Each run invokes the actual Bash helper with isolated temporary XDG directories.
The existing curl/DNS fixtures provide station data and fail one request type
on every mirror. No public API, user data, desktop configuration, or audio device
is used. UI results run the production `fetchProcess.onExited` and
`setStationList` code in a JavaScript VM with widget callbacks stubbed. This is
behavioral evidence, not a rendered screenshot or a live service test.

The regression test failed against the baseline because the incomplete search
exited successfully. It passes after the fix, including nonempty partial
responses, untouched runtime results, and removal of temporary search files.
Successful country aliases, genre queries, and genuinely empty searches still
pass. The QML completion test verifies that a failed search preserves the local
preview and reports the error.

Validation:

```bash
node tests/search.test.mjs
node tests/search-queue.test.mjs
dbus-run-session -- ./tests/run
```

All passed after the fix. There is no layout change.
