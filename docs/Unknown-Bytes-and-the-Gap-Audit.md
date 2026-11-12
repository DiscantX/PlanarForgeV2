# Unknown Bytes and the Gap Audit

A schema describes the bytes its authors understand. Real game files contain others: padding, fields no one has identified, leftovers from the original tools. Whether to keep, ignore or discard such bytes is a design question as much as a technical one. This article describes how the project finds unmapped bytes, how it decides they are safe, and how it keeps that decision explicit.

It builds on [Round-trip Failure Taxonomy](Round-trip-Failure-Taxonomy.md) and [Shared and Orphaned Data Blocks](Shared-and-Orphaned-Data-Blocks.md). The history is in the [Fidelity Fixes log](archive/Engineering-Log-Fidelity-Fixes.md) (2026-04-02 and 2026-04-03) and the [WED Upgrade log](archive/Engineering-Log-WED-Upgrade.md) (*Gap Audit Closure* and *Audit Performance Hardening*).

## The question

Passing round-trip tests proves that nothing was lost *in the files tested*. It does not say how many bytes were preserved only by accident, for instance by a blanket "keep the tail" rule. The 2026-04-02 entry puts the goal plainly: answer "are unmapped bytes meaningful?" with evidence, not assumptions.

## Three ways bytes are preserved

| Mechanism | What it keeps | When it applies |
|-----------|---------------|-----------------|
| Unknown bits in `_unknown` | Undefined bits of a bitmask or bitfield | Always |
| `bytes` fields | Declared but uninterpreted blocks (padding, unknown regions) | Always |
| `trailing_data` | Anything after the last structured section | Unmodified resources only |

The first two are explicit in the schema: the author has said "these bytes exist and I do not understand them". The third is implicit and silent, which is why it needs auditing. `trailing_data` is captured by the parser from the highest extent any section reached, written back only when the resource has not been modified, and never exposed to the schema ([Shared and Orphaned Data Blocks](Shared-and-Orphaned-Data-Blocks.md#unreferenced-data) explains why the extent matters).

## Byte claims

Every field the parser reads *claims* a byte range of the file. The parser can record these claims, merge overlapping ones, and then subtract them from the file's extent. What is left is the set of **unmapped gaps**: ranges that no field read.

Gaps come in two kinds:

- **Internal gaps**, between claimed ranges, typically alignment padding or sections the schema does not know about.
- **Tail gaps**, after the last claimed range.

Claim tracking is **off unless the audit is requested**. The log records that always-on tracking added measurable runtime cost, so the parser records claims only when auditing is enabled (2026-04-03, *Gap Audit Performance Tuning*).

## What a gap report says

The audit is part of the fidelity test run. For each gap it records enough to classify the bytes without opening a hex editor:

- byte range and size
- the proportion of nonzero and `0xFF` bytes, and the entropy
- the neighbouring claimed fields (`prev` and `next`)
- any pointers elsewhere in the file that point *into* the gap
- hints about what structure the bytes might be
- hex head and tail, and an ASCII preview

Gaps are classified by risk. A gap that is all zeros and unreferenced is almost certainly padding. A nonzero gap, or one that something points into, is a candidate for a missing schema section, as with the unmodelled CRE spell groups, which looked like noise until inspection showed regular 16-byte entries. Summaries are aggregated by game and schema so that patterns show up (for example, many files of one type sharing the same gap).

## The allowlist

Some gaps remain after investigation. Near Infinity marks several regions as "Unused bytes?", and in the cases examined the audit found no reference to them. Ignoring whole files would hide future regressions, so the project suppresses gaps **by exact location**.

`tools/tests/gap_allowlist.json` holds rules matched on game, schema, resource name, and start and end offsets, with optional constraints on size, kind, classification and risk. Each rule carries an identifier and a note recording why it is believed safe. Representative rules in the log are PSTEE creatures such as `3PLANEA` (an unused placeholder with no in-game references), PSTEE and BGEE area-geometry (WED) files, and four PSTEE areas (`AR0501`, `AR1001`, `AR3017`, `AR13WZ`) closed in the final pass.

Because the match is exact, a rule stops applying if the file changes, the schema changes the offsets, or a new gap appears next to the old one. Reports distinguish **active** from **suppressed** gaps and total the suppressed bytes, naming the rule responsible. The allowlist stores names, sizes and offsets only, which is consistent with the [Game Asset Policy](Game-Asset-Policy.md).

## Cost and control

The test suite has options to adjust the cost of auditing:

| Option | Purpose |
|--------|---------|
| `--gap-detail-level summary` | Fastest; counts and totals |
| `--gap-detail-level nonzero` | Default; full diagnostics for nonzero gaps |
| `--gap-detail-level full` | Deep diagnostics for every gap |
| `--profile-performance`, `--profile-sort`, `--profile-limit` | Profile the run |

Offset-like fields are indexed once per resource and reused when checking which gaps are pointed into.

## What the audit does and does not establish

It establishes that every unmapped byte in the tested files is either modelled, preserved by an explicit mechanism, or listed in the allowlist with a reason. The 2026-04-03 milestone entry records zero failures on that basis.

It does not establish that the unmapped bytes are meaningless to the game. "Unused" in the allowlist means that no reference was found by the project and by Near Infinity, which is evidence, not proof. Two limits follow:

- The audit covers only the files in the installed games it was run against.
- Preservation of `trailing_data` is for unmodified files. A modified resource is rewritten from the model, so any meaning in unmapped bytes is lost unless the schema captures it.

## Guidance

1. Treat a new active gap as a prompt to model something, not to suppress it.
2. Add an allowlist rule only with a note saying what was checked.
3. Prefer an explicit `bytes` field for a known-unknown block over leaving it to `trailing_data`.
4. Rerun the audit after any schema change that moves offsets, since exact rules depend on them.

## Discrepancies noticed while writing

- The allowlist file contains 15 rules. The log lists 7 in its first entry (PSTEE CRE, PSTEE WED, BGEE WED) and 4 in its closing entry, which is 11. The repository is authoritative; the log was not necessarily exhaustive.
- The WED upgrade log reports the audit work under its own dates, with the same content as the fidelity log. They describe one system.

## See also

- [Round-trip Fidelity](Round-trip-Fidelity.md)
- [Round-trip Failure Taxonomy](Round-trip-Failure-Taxonomy.md)
- [Game Asset Policy](Game-Asset-Policy.md)
