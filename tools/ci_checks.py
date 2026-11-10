#!/usr/bin/env python3
"""Select an explicit GitLab comparison base; never fetch or publish here."""
import os
import sys
from release import main


def run():
    tag = os.environ.get("CI_COMMIT_TAG")
    if tag:
        return main(["verify-tag", "--tag", tag])
    if os.environ.get("CI_PIPELINE_SOURCE") == "merge_request_event":
        # before_script fetched the target tip into FETCH_HEAD. A stale source
        # branch must update instead of dropping newly merged work/fragments.
        branch = os.environ["CI_MERGE_REQUEST_SOURCE_BRANCH_NAME"]
        target = os.environ["CI_MERGE_REQUEST_TARGET_BRANCH_NAME"]
        base = os.environ.get("CI_MERGE_REQUEST_TARGET_BRANCH_SHA") or "FETCH_HEAD"
        return main(["validate", "--base", base, "--branch", branch, "--target", target,
                     "--commits", "--commit", os.environ["CI_MERGE_REQUEST_TITLE"]])
    return main(["validate", "--base", "HEAD^1", "--branch", "main", "--commits"])


if __name__ == "__main__":
    sys.exit(run())
