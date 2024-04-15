#!/bin/bash

# Clobber upload an existing electron riscv64 release
# Usage: ./clobber-upload-release.sh <version> <riscv-revision>

set -e

if [ $# -ne 2 ]; then
  echo "Usage: ./clobber-upload-release.sh <version> <riscv-revision>
env vars:
    GITHUB_TOKEN: GitHub token with repo access
    ARTIFACTS_DIR: Directory containing the subdirectories named by <version>-<riscv-revision>"
  exit 1
fi

# Set default ARTIFACTS_DIR

if [ -z "$ARTIFACTS_DIR" ]; then
  ARTIFACTS_DIR=/data/electron-ci/artifacts/releases
fi

# First use gh CLI to figure out whether the release exists
repo=riscv-forks/electron-riscv-releases
version=$1
riscv_revision=$2

if gh release view v$version > /dev/null 2>&1; then
  echo "Release v$version exists, will clobber upload"
  release_action=edit
else
  echo "Release v$version does not exist, will create a new release"
  release_action=create
fi

# Create or edit the release

gh -R "$repo" release $release_action "v$version" \
    -t "Electron v$version for 64 Bit RISC-V" \
    --notes "Latest Electron v$version for riscv64
This release will be re-uploaded if a new riscv64 revision is made.
Original release: https://github.com/$repo/releases/tag/v$version.riscv$riscv_revision"

# Upload the artifacts

gh -R "$repo" release upload --clobber "v$version" $(find "$ARTIFACTS_DIR/v$version-$riscv_revision" -type f -size -2147483648c)
