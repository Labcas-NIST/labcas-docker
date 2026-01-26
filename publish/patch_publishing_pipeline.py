import os
import copy

def patch_publishing_pipeline():
    import pathlib
    import sys

    # Read the original publishing_pipeline.py
    # Handle both flat-layout and src-layout repositories
    pipeline_path = "/opt/publish/publishing_pipeline.py"

    with open(pipeline_path, "r") as f:
        lines = f.readlines()

    # Patch lines containing contains='_labcasmet_' to remove leading underscore
    for i, line in enumerate(lines):
        if "contains='_labcasmet_'" in line:
            lines[i] = line.replace("contains='_labcasmet_'", "contains='labcasmet_'")

    # Fix run_pipeline_unsanitized call signature (publish_id arg required).
    for i, line in enumerate(lines):
        if "run_pipeline_unsanitized(collection, collection_subset, steps)" in line:
            lines[i] = line.replace(
                "run_pipeline_unsanitized(collection, collection_subset, steps)",
                "run_pipeline_unsanitized(collection, collection_subset, publish_id, steps)",
            )

    # Write back the modified file
    with open(pipeline_path, "w") as f:
        f.writelines(lines)

if __name__ == "__main__":
    patch_publishing_pipeline()

 
    
