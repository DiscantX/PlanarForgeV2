# Optimization Log

### Completed

1. **Random Access BIF Reading**: Optimized resource loading by calculating BIF entry offsets directly and seeking to data, bypassing full `BinaryParser` overhead for container metadata.

2. **Chitin Lookup Caching**: Implemented O(1) resource lookups via a hash map generated at startup.

3. **Resource Type Mapping**: Automated conversion of integer resource types to string extensions (e.g., 1002 -> ITM).

4. **File Handle Optimization**: Reduced filesystem overhead by avoiding redundant file openings during BIF resource extraction.

5. **BIF I/O Bottleneck Fix**: Eliminated full parsing of BIF indices; `BiffHandler` now seeks directly to resource data using the index provided by Chitin.

### Current Bottlenecks & Future Work

1. **Resource Indexing**: Shifting from full `to_dict()` caching to a projection-based index to reduce memory footprint and startup time.

2. **Undo/Redo System**: Implementing a Command pattern to support non-destructive editing in Stage 3.

3. **BAM Parsing**: Determining whether to treat BAMs as opaque assets or source-controlled project files.

4. **Layer 2 Schema Design**: Defining the clean project-level schemas for CRE, ITM, and ARE.