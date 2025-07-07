import os
import copy

def patch_publishing_pipeline():
    import pathlib
    import sys

    # Read the original publishing_pipeline.py
    # Handle both flat-layout and src-layout repositories
    candidate_paths = [
        "/opt/publish/publishing_pipeline.py",
        "/opt/publish/src/publishing_pipeline.py",
        "/opt/publish/tasks/publishing_pipeline.py",
        "/opt/publish/src/tasks/publishing_pipeline.py",
    ]
    # Patch *all* copies that exist (flat-layout, src-layout, tasks package).
    # The first one becomes the "primary" used later for the keep-alive append.
    existing_paths = [p for p in candidate_paths if os.path.exists(p)]
    if not existing_paths:
        sys.stderr.write("ERROR: publishing_pipeline.py not found in any expected location\\n")
        sys.exit(1)
    pipeline_path = existing_paths[0]  # primary copy
    with open(pipeline_path, "r") as f:
        lines = f.readlines()

    # Find the line with compare_with_solr call
    target_line = None
    for i, line in enumerate(lines):
        if "compare_with_solr(os.path.join(metadata_dir, collection), publish_id, collection, copy.deepcopy(metadata_walker))" in line:
            target_line = i
            break

    if target_line is None:
        print("Could not find compare_with_solr call in publishing_pipeline.py")
        sys.exit(1)

    # Insert debug print statements before the compare_with_solr call
    debug_lines = [
        '        print(f"DEBUG: metadata_dir={metadata_dir}")\n',
        '        print(f"DEBUG: collection={collection}")\n',
        '        print(f"DEBUG: publish_id={publish_id}")\n',
    ]
    lines = lines[:target_line] + debug_lines + lines[target_line:]

    # ------------------------------------------------------------------
    # Also inject prints right before metadata walker creation so we can
    # verify parameters passed to create_generic_file_walker.
    # ------------------------------------------------------------------
    walker_line = None
    for i, line in enumerate(lines):
        if (
            "metadata_walker = create_generic_file_walker(temp_walker" in line
            and "contains='_labcasmet_'+publish_id" in line
            and "subset=os.path.join(metadata_dir, collection)" in line
        ):
            walker_line = i
            break

    if walker_line is not None:
        walker_debug = [
            '        print(f"DEBUG: temp_walker={temp_walker}")\n',
            '        print(f"DEBUG: contains=_labcasmet_{publish_id}")\n',
            '        print(f"DEBUG: subset={os.path.join(metadata_dir, collection)}")\n',
        ]
        lines = lines[:walker_line] + walker_debug + lines[walker_line:]
    # Prefix the "Finally in publish ..." message with "1 "
    for i, ln in enumerate(lines):
        if "Finally in publish where publish_id" in ln and "1 📚 Finally" not in ln:
            lines[i] = ln.replace("📚 Finally", "1 📚 Finally")
    
    # Append END to the metadata walker creation message
    for i, ln in enumerate(lines):
        if "Creating metadata walker" in ln and "END" not in ln:
            lines[i] = ln.replace("Creating metadata walker", "Creating metadata walker END")

    # Replace abort-on-missing collection path with auto-create logic
    for i, ln in enumerate(lines):
        if "Fix the collection and archive_dir" in ln:
            # Replace the diagnostic print
            lines[i] = '        print(f"WARNING: archive dir {collection_archive_dir} does not exist; creating it")\n'
            # Replace the subsequent raise ValueError (if present)
            if i + 1 < len(lines) and "raise ValueError" in lines[i + 1]:
                lines[i + 1] = '        os.makedirs(collection_archive_dir, exist_ok=True)\n'

    # Write back the modified file
    with open(pipeline_path, "w") as f:
        f.writelines(lines)
    # Replicate the same modifications to any additional copies
    for _p in existing_paths[1:]:
        with open(_p, "w") as _fh:
            _fh.writelines(lines)

if __name__ == "__main__":
    patch_publishing_pipeline()

    # Append code to keep publishing_pipeline.py running continuously
    # Determine which publishing_pipeline.py we patched so that the keep-alive
    # loop is appended to the correct file regardless of repo layout.
    candidate_paths = [
        "/opt/publish/publishing_pipeline.py",
        "/opt/publish/src/publishing_pipeline.py",
        "/opt/publish/tasks/publishing_pipeline.py",
        "/opt/publish/src/tasks/publishing_pipeline.py",
    ]
    pipeline_path = next((p for p in candidate_paths if os.path.exists(p)), None)
    if pipeline_path is None:
        raise SystemExit("ERROR: cannot locate publishing_pipeline.py for keep-alive append")
    with open(pipeline_path, "a") as f:
        f.write("\n\n# Added by patch to keep process running\n")
        f.write("import time\n")
        f.write("while True:\n")
        f.write("    time.sleep(10)\n")