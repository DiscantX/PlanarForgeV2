# Contributing

The full conventions are in [Workflow and Conventions](docs/Workflow-and-Conventions.md). In short:

1. **Open an issue first.** Use one of the issue templates. Every issue needs at least two labels: one `type:` (`bug`, `feature`, `docs`, `refactor`, `chore`) and one `area:` (`core`, `schema`, `driver-ie`, `viewer`, `tests`, `wiki`). The templates set the `type:` label; add the `area:` label yourself if the template could not.
2. **Make the change on a branch** and open a pull request against `main`. Keep it to one issue.
3. **Close the issue from the pull request** by writing `Closes #N` in its description.
4. **Update the documentation** in `docs/` in the same pull request when behaviour or design changes.
5. **Never commit game files.** Not even small ones, and not in tests. See the [Game Asset Policy](docs/Game-Asset-Policy.md).

If one pull request is based on another's branch (a "stacked" pull request), retarget it to `main` as soon as the first one merges.
