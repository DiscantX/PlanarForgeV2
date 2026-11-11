# Workflow and Conventions

How work is done on PlanarForgeV2, so that a returning contributor, human or AI, can pick it up cold.

## Issues and pull requests

* **Every change starts as an issue.** Describe the problem and the scope. Each issue carries at least two labels: one `type:` and one `area:`.
* **Every change lands as a pull request.** The pull request description says `Closes #N`, so that merging it closes the issue. Pull requests are kept small, one issue each.
* **Stacked pull requests need care.** If one pull request is based on another's branch, retarget it to `main` as soon as the first merges. Merging a stacked pull request into a branch that has already been merged leaves its changes stranded off `main`.
* **Documentation travels with the code.** The documentation lives in `docs/`, so one pull request can change both.

## Labels

| Axis | Labels |
|------|--------|
| `type:` | `bug`, `feature`, `docs`, `refactor`, `chore` |
| `area:` | `core`, `schema`, `driver-ie`, `viewer`, `tests`, `wiki` |

More `area:` labels will be added when new components, such as the user interface, appear.

## Writing the documentation

* The register is scholarly but accessible: assume a capable reader who has never met the Infinity Engine.
* Pages cross-reference each other with relative markdown links, for example `[Round-trip Fidelity](Round-trip-Fidelity.md)`. The wiki-style `[[double bracket]]` links are not used.
* Claims about the formats cite their source, preferably [IESDP](https://iesdp.bgforge.net/) or [Near Infinity](https://github.com/NearInfinityBrowser/NearInfinity), and say so when a claim rests only on a hex dump.
* Pages that describe unmerged or unverified work say so explicitly.
* Project state lives here in `docs/`, not in separate files such as `MEMORY.md`, `PROGRESS.md` or `ARCHITECTURE.md`. Start from the [documentation index](README.md) and the [Project Status](Project-Status.md).

## Diagnosing format problems

The habits that have worked:

1. **Diagnose before changing code.** Log what the pipeline does at each step and compare it with Near Infinity's output for the same file.
2. **Use a hex editor for ground truth** when Near Infinity does not show the raw bytes, then compare with the parsed result.
3. **Deliver small changes** that can be applied and tested one at a time.
4. **Do not stack fixes on an unverified guess.** Several earlier problems, TIS in particular, grew out of changes made without a confirmed diagnosis.

## Game files

Real game data is needed to verify most format work, and it must never enter the repository. See the [Game Asset Policy](Game-Asset-Policy.md). Only Baldur's Gate II: Enhanced Edition is currently installed locally, so work on other games waits until they are installed.
