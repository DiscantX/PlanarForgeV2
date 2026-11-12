# Debugging Lessons

Between 17 March and 3 April 2026 the project took its schema-driven reader and writer from failing on most files to passing every round-trip test. The route was not direct. This article collects what that work taught about *how* to debug the engine, as distinct from what was wrong with it. The technical findings are in the companion articles; here the aim is to extract practices that would have shortened the path.

The sources are the postmortem and related entries of the [Fidelity Fixes log](archive/Engineering-Log-Fidelity-Fixes.md), and the [WED Upgrade log](archive/Engineering-Log-WED-Upgrade.md). Each lesson is tied to the episode that taught it. Where the current code has since adopted a lesson, that is stated.

## Summary

| # | Lesson | Taught by |
|---|--------|-----------|
| 1 | A crash is evidence; do not silence it | The defensive read check |
| 2 | Suspect the inputs before the component | Loader name collisions |
| 3 | Test the harness as well as the code | The test suite's own collision bug |
| 4 | Decide first whether it is a read or a write error | The IWD2 duplicate fields |
| 5 | Check a premise with the smallest possible probe | The offset-correction experiment |
| 6 | Turn recurring mistakes into validation | Duplicate field names |
| 7 | Prove the code path runs | The singular/plural section names |
| 8 | A passing test is not proof of fidelity | The whole-file passthrough |
| 9 | When patches multiply, question the model | Feature blocks; the WED writer |
| 10 | Replace assumptions with measurements | The gap audit |
| 11 | Look for the same fault in sibling formats | IWD2 and Enhanced Edition actors |

## 1. A crash is evidence; do not silence it

Many files crashed the parser with absurd counts and offsets. A defensive check in `BinaryParser.read` stopped the crashes by refusing to read past the end of the file. The crashes disappeared and the underlying fault stayed: the parser was being given the bytes of the wrong resource. The log's verdict is that the fix treated the symptom and removed the best clue. The check was reverted and the crashes returned, pointing at the resource loader.

The principle is that a robust system should fail clearly on fundamentally invalid input, not absorb it. An early failure with a precise message is more useful than a later one that is easy to misread. A related case: a crash reading a 16-byte integer in IWD2 was first "fixed" by letting the reader handle larger integers, though the real error was a schema that should never have asked for an integer there ([Round-trip Failure Taxonomy](Round-trip-Failure-Taxonomy.md)).

## 2. Suspect the inputs before the component

When a low-level component fails, its inputs belong in the investigation. The parser was correct; the loader keyed resources by name alone, so `CARRIO.ITM` and `CARRIO.CRE` collided and the item parser received a creature's bytes. The signature on the first byte (a mismatch of `S` against `I`) was visible from the start. A byte-zero mismatch, a wrong signature or counts that look like text all mean that the component is probably reading the wrong thing.

A practical way to make this routine is a unit test of the parser on static, known-good byte arrays. If it passes, the investigation moves to whatever feeds it.

## 3. Test the harness as well as the code

After the loader was fixed, many tests still failed, because the test suite fetched the original bytes with the same name-only lookup. It compared a saved item against a spell or store file of the same name. A test that disagrees with a correct result is a cost twice over: it hides progress and suggests faults that do not exist. When results look wrong in a way that does not match the change just made, check what the test is comparing before changing the code.

## 4. Decide first whether it is a read or a write error

For the final stubborn IWD2 item failure, theory had produced several hypotheses without narrowing anything. A single `print()` of the resource in memory showed that the parsed value was already wrong, so the fault lay in reading and not in writing. That one observation removed most of the hypotheses. The same split appears in later work: in the area drift cases the wrong values were present on the first read, and the zeroed bytes in the output were a consequence ([Offset Drift and Schema Versioning](Offset-Drift-and-Schema-Versioning.md)).

The log's own phrase is "simple, directed debugging": inspect data at the boundary between two components, and learn which side is at fault before reasoning further.

## 5. Check a premise with the smallest possible probe

An `offset_correction` feature was built on the idea that an IWD2 pointer was off by 16 bytes. It took a full development cycle to implement and revert, and a direct look showed the pointer in the file was correct all along. A tiny script reading one integer at a known offset would have refuted the premise in minutes. Before building on a hypothesis about the file format, test the hypothesis against the file.

## 6. Turn recurring mistakes into validation

The IWD2 fix came down to fields sharing a name, which silently overwrite each other. The log recommended that the schema loader reject such schemas. This was adopted: `core/schema_loader.py` now raises an error for a duplicate field name within a section, and, as a companion, for fields that do not follow one another contiguously by offset and size (virtual zero-size fields excluded). History shows the duplicate-name check was added on 18 March 2026, the day of the fix. The second check bears directly on [offset drift](Offset-Drift-and-Schema-Versioning.md), since it catches a mis-sized field inside a section at load time.

Two related cases are *not* covered by anything this article could find. Duplicate enumeration labels (the `Food` label that caused the `00GENIR` mismatch) are not checked by the loader, and drift between a section's declared entry size and the file's actual one can only be found by running against real files. Both are candidates for further validation.

## 7. Prove the code path runs

For the item feature blocks, three successive fixes left the checksum unchanged. The cause, found only after diagnostic logging, was that the special-case code never executed because the parser tested plural section names where the schemas used singular ones ([Shared and Orphaned Data Blocks](Shared-and-Orphaned-Data-Blocks.md#how-the-bug-hid-itself)). The WED work repeated the pattern in a different form: trace logging at specific offsets showed the right bytes being written and the wrong bytes surviving, which relocated the problem to how the writer positioned blocks.

When a change has no effect, the first suspicion should be that it is not being exercised. A log line or counter at the point of the change answers that quickly.

## 8. A passing test is not proof of fidelity

A temporary whole-file passthrough made unmodified IWD2 creatures round-trip while bypassing serialisation entirely. It was correctly removed and the missing structure was modelled. The same concern applies to blanket tail preservation, which can mask unmodelled data, and it is the reason the project later built the [gap audit](Unknown-Bytes-and-the-Gap-Audit.md) to say exactly which bytes are preserved, by what mechanism and with what justification.

Fidelity also has a scope. The project requires byte identity only for unmodified files; a modified file must be valid and semantically correct, not a copy of the original's quirks. Stating that scope early prevented a good deal of misdirected effort.

## 9. When patches multiply, question the model

Two series stand out. The feature-block problem took five entries before its cause was found. The WED writer took roughly nine entries on one day, each adding a rule for choosing among blocks that claimed the same offset. In both, the growing logic was compensating for a model that created the ambiguity. The WED overhaul replaced per-parent jumps with flat global sections and the arbitration rules disappeared ([WED V1.3 Engine Upgrade](WED-V1.3-Engine-Upgrade.md)). This is an interpretation of the record and is offered as such, but the pattern is consistent: after the second fix that does not change the result, ask whether the data model is right.

## 10. Replace assumptions with measurements

The gap audit exists because "are unmapped bytes meaningful?" had been answered by assumption. Recording byte claims, classifying each gap by content and by what points into it, and suppressing only by exact location turned a belief into a report that can be re-run. The same attitude produced the practice of verifying entry sizes against Near Infinity and real files, and the discovery that a specification can itself be wrong or out of date (the tilemap entry size).

## 11. Look for the same fault in sibling formats

The IWD2 area actor error was recognised as identical to one already fixed for the Enhanced Edition area schema, which shortened the diagnosis. When a structural error is found in one schema, check the sibling schemas for the same structure.

## A note on the logs themselves

The logs contain several entries that were later corrected, and statements that no longer match the repository (see the discrepancies in [Round-trip Failure Taxonomy](Round-trip-Failure-Taxonomy.md#discrepancies-noticed-while-writing)). That is a lesson too. Records of debugging are valuable because they preserve what was tried and why it failed, but a reader should treat them as a history, not a specification. The repository is authoritative. The logs are therefore frozen in the [archive](archive/README.md), and current knowledge lives in the articles that cite them.

## A checklist

1. Is the first failing byte in the right resource? Is the right schema selected?
2. Is the value wrong on read, or only on write? Inspect the parsed data.
3. Does the entry size implied by the file match the schema?
4. Are there duplicate names, labels or overlapping offsets?
5. Does the changed code actually run? Log it.
6. Is the test comparing what you think it compares?
7. After two fixes with no effect on the result, reconsider the model.
8. Before building a feature on a hypothesis about the file, probe the file.

## See also

- [Round-trip Failure Taxonomy](Round-trip-Failure-Taxonomy.md)
- [Shared and Orphaned Data Blocks](Shared-and-Orphaned-Data-Blocks.md)
- [Unknown Bytes and the Gap Audit](Unknown-Bytes-and-the-Gap-Audit.md)
- [Offset Drift and Schema Versioning](Offset-Drift-and-Schema-Versioning.md)
- [WED V1.3 Engine Upgrade](WED-V1.3-Engine-Upgrade.md)
- [Workflow and Conventions](Workflow-and-Conventions.md)
