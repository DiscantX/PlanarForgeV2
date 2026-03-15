import os
import fnmatch
from pathlib import Path

def get_ignore_patterns(root_path):
    """
    Reads .gitignore from the root path and returns a list of patterns.
    Also adds .git/ to the ignore list by default.
    """
    patterns = []
    ignore_file = root_path / ".gitignore"
    if ignore_file.exists():
        try:
            with open(ignore_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        patterns.append(line)
        except Exception as e:
            print(f"[Warning] Could not read .gitignore: {e}")
    
    # Always ignore .git directory
    patterns.append(".git/")
    return patterns

def should_ignore(path, root_path, patterns):
    """
    Determines if a path should be ignored based on the patterns.
    Supports basic gitignore syntax:
    - 'name' matches file/dir name anywhere
    - '/name' matches relative to root
    - '**/name' matches name anywhere
    - 'name/' matches only directories
    """
    rel_path = path.relative_to(root_path).as_posix()
    name = path.name

    for pattern in patterns:
        # Check if pattern targets directories only
        must_be_dir = pattern.endswith("/")
        clean_pattern = pattern.rstrip("/")

        if must_be_dir and not path.is_dir():
            continue

        # Handle recursive marker
        if clean_pattern.startswith("**/"):
            suffix = clean_pattern[3:]
            if fnmatch.fnmatch(name, suffix):
                return True
        
        # Handle rooted path
        elif "/" in clean_pattern:
            if fnmatch.fnmatch(rel_path, clean_pattern):
                return True
        
        # Handle simple filename match
        else:
            if fnmatch.fnmatch(name, clean_pattern):
                return True

    return False

def print_tree(directory, root_path, prefix="", ignore_patterns=None):
    entries = list(directory.iterdir())
    # Sort: directories first, then files
    entries.sort(key=lambda p: (not p.is_dir(), p.name.lower()))

    filtered = [e for e in entries if not should_ignore(e, root_path, ignore_patterns)]
    count = len(filtered)

    for i, entry in enumerate(filtered):
        connector = "└─ " if i == count - 1 else "├─ "
        print(f"{prefix}{connector}{entry.name}{'/' if entry.is_dir() else ''}")

        if entry.is_dir():
            extension = "    " if i == count - 1 else "│   "
            print_tree(entry, root_path, prefix + extension, ignore_patterns)

if __name__ == "__main__":
    # Assume script is in tools/ and project root is one level up
    root = Path(__file__).resolve().parent.parent
    patterns = get_ignore_patterns(root)
    print(f"{root.name}/")
    print_tree(root, root, ignore_patterns=patterns)