# kilix-license

`kilix-license` is the single licence authority for Kilix (OD-AJ). It
owns licence records stored by text digest, the verbatim first-use
screen, agreement capture, digest-bound receipts, and binding-scoped
`covers` / `require`.

This `0.1.0` LIC1 state is a local repository: identity, hermetic
harness, weight-absence guard, authority schema, and coverage. Model
records land in LIC2. The repository licence file is MIT; wave LIC3
re-confirms it (OD-AV).

## Publication status

The repository is **local-only**. It has no remote and is not authorised
for a push or for GitHub repository creation. See `PUBLICATION.md`.

Runtime code uses the Python standard library only.

## Development

The development environment is frozen to Python 3.12.8 and uv 0.12.5.

```sh
uv sync --frozen --python 3.12.8
make check
```

`make check` syncs the frozen environment, runs the test suite, and
builds installable artifacts.
