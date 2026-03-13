Publish a new release of Coral to PyPI. The user provides the version number as $ARGUMENTS (e.g. "1.0.0").

Follow these steps in order:

## 1. Bump the version

Update `version` in `pyproject.toml` to the provided version number.

## 2. Commit the version bump

Stage `pyproject.toml` and create a commit:
```
chore: bump version to <version>
```

## 3. Tag the release

Create an annotated git tag `v<version>` with release notes. Generate the release notes by summarizing the commits since the last tag:
```
git log $(git describe --tags --abbrev=0 2>/dev/null || git rev-list --max-parents=0 HEAD)..HEAD --oneline
```

Format the tag message as:
```
Coral v<version>

<one-line summary of this release>

Highlights:
- <bullet points summarizing key changes>
```

## 4. Push to remote

Push the commits and the new tag:
```
git push && git push origin v<version>
```

## 5. Build the distribution

Build the sdist and wheel:
```
.venv/bin/python -m build
```

Verify the correct version appears in `dist/`.

## 6. Upload to PyPI

Upload using twine (ask the user for confirmation before this step):
```
.venv/bin/python -m twine upload dist/agent_coral-<version>*
```

## 7. Summary

Report back with:
- The git tag created
- The PyPI package files uploaded
- A link to the PyPI project page: https://pypi.org/project/agent-coral/
