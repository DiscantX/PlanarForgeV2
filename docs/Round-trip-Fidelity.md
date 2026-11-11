# Round-trip Fidelity

The primary purpose of our round-trip testing is to verify that our read/write operations can produce valid game files without any data loss when no modifications are made.

## Fidelity Classifications

### 1. Bitmask Fidelity Loss (Data Loss)

* **The Mechanism**: The `Bitmask` field type converts integers into dictionaries.
* **The Error**: Bits set in the original file not defined in the schema are discarded during `read`.
* **Impact**: Checksum mismatch.

### 2. Orphaned Data Loss

* **The Mechanism**: Effects referenced by abilities but outside the global effect count.
* **The Error**: The parser initially ignored these during logical counting.
* **Impact**: Critical truncation.

### 3. Binary Repacking & Offset Shifts (False Positives)

* **The Mechanism**: `BinaryParser.write` recalculates offsets tightly.
* **The Error**: Original files contain gaps or non-standard ordering.
* **Impact**: MD5 mismatch on semantically identical data.

## The Unknown Byte Policy

1. **Unmodified Files**: We strive for 100% byte-perfect fidelity. We use an "Automatic Tail Preservation" buffer to capture unreferenced data at the end of files.
2. **Modified Files**: Once a user begins editing (moving to Layer 2), unknown byte preservation stops. The system produces a clean, repacked output based strictly on mapped fields.

## Gap Audit Framework

To verify fidelity without manually checking hex dumps, we use a gap audit framework that identifies unmapped bytes and classifies them:

* **Classification**: `nonzero_unreferenced`, `pointer_referenced_nonzero`, or `tail_gap`.
* **Risk Assessment**: Determines if the gap is likely critical data or "zombie" garbage.
* **Allowlisting**: Verified safe gaps are suppressed in test results using `tools/tests/gap_allowlist.json`.

## Troubleshooting Steps

When a fidelity test fails:

1. Check for **Offset Drift**: Ensure field sizes in the schema match the binary structure.
2. Check for **Duplicate Field Names**: Ensure every field in a section has a unique name to prevent data overwriting.
3. Check for **Shared Offsets**: In formats like WED, verify that multiple sections aren't clobbering each other's data during the write pass.

---

For a detailed chronological history of the bugs found and fixed during the development of the fidelity engine, see the [Engineering Log Fidelity Fixes](Engineering-Log-Fidelity-Fixes.md).