import sys
from pathlib import Path


def main():
    """
    Remove hard-coded overrides that force the collection to 'Basophile'
    (and related variables) so that environment variables supplied at
    runtime take precedence.
    """
    # Look for configs/basic.py in both flat-layout and src-layout checkouts.
    candidate_paths = [
        Path("/opt/publish/configs/basic.py"),
        Path("/opt/publish/src/configs/basic.py"),
    ]
    cfg_paths = [p for p in candidate_paths if p.exists()]
    if not cfg_paths:
        sys.stderr.write(
            "patch_basic_env_override.py: configs/basic.py not found in any expected location\n"
        )
        sys.exit(1)
    # Use the first match for reading; we will replicate the patched contents to all.
    cfg_path = cfg_paths[0]

    original_lines = cfg_path.read_text().splitlines(keepends=True)
    patched_lines = []
    skip_block = False
    in_original_section = False  # True once we reach the separator for original code

    for line in original_lines:
        stripped = line.strip()

        # Detect transition into the original portion of the file that follows
        # the header injected by labcas-docker.  We need to keep this separator
        # but also remember that subsequent lines belong to the "original"
        # section where hard-coded overrides live.
        if stripped.startswith("# ---- original below ----"):
            in_original_section = True
            patched_lines.append(line)
            continue

        # Start of the override block we want to remove
        if stripped.startswith("# For jpl-labcas"):
            skip_block = True
            continue

        # If we're inside the override block, skip lines that set the variables
        if skip_block:
            if stripped == "" or stripped.startswith("#"):
                # End the skip when we hit a blank line or another comment
                skip_block = False
            # Always skip the variable assignment lines inside this block
            continue

        # Additionally guard against any stray hard-coded overrides
        if (
            ("'Basophile'" in stripped and stripped.startswith("collection"))
            or stripped.startswith("collection_subset = None")
            or stripped.startswith("publish_id = None")
            or stripped.startswith("steps = [")
            or (in_original_section and stripped.startswith("archive_dir"))
        ):
            # Skip undesirable hard-coded overrides found in the original section.
            continue

        patched_lines.append(line)

    cleaned_text = "".join(patched_lines)
    for _p in cfg_paths:
        _p.write_text(cleaned_text)

    print("patch_basic_env_override.py: removed hard-coded Basophile overrides from basic.py")


if __name__ == "__main__":
    main()