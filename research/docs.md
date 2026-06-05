# Project webpage

`index.html` is a self-contained, dependency-free page that walks through the
Semantic Assembly idea space (problem → thesis → format → projection → validator →
proof → status).

## View it locally

Just open the file:

```console
# macOS
open docs/index.html
# Linux
xdg-open docs/index.html
# Windows
start docs/index.html
```

Or serve the folder:

```console
python -m http.server -d docs 8000   # then visit http://localhost:8000
```

## Publish with GitHub Pages

Settings → Pages → **Build and deployment** → Source: *Deploy from a branch* →
Branch: `main`, folder: **`/docs`**. The site appears at
`https://<owner>.github.io/<repo>/`. (`.nojekyll` is included so the static HTML
is served as-is.) The "View the repository" links auto-resolve to the correct
GitHub URL when served from a `*.github.io` host.
