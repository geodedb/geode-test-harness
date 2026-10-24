#!/usr/bin/env bash
# Refresh a CI dependency at one commit without discarding local changes.
set -euo pipefail

if [[ $# != 2 ]]; then
    echo "usage: ci-clone.sh URL DESTINATION" >&2
    exit 2
fi
url=$1
destination=$2

if [[ -d "$destination/.git" || -f "$destination/.git" ]]; then
    # Older CI jobs embedded their short-lived job credential in the URL.
    # Compare the repository identity without printing or retaining it.
    origin=$(git -C "$destination" remote get-url origin)
    identity=$(printf '%s\n' "$origin" | sed -E 's#(https?://)[^/@]+@#\1#')
    if [[ "$identity" != "$url" ]]; then
        echo "ci-clone: destination belongs to a different repository" >&2
        exit 1
    fi
    if [[ -n $(git -C "$destination" status --porcelain) ]]; then
        echo "ci-clone: destination has local changes; refusing to replace them" >&2
        exit 1
    fi
    git -C "$destination" remote set-url origin "$url"
    git -C "$destination" fetch --depth 1 origin HEAD
    git -C "$destination" checkout --detach FETCH_HEAD
else
    mkdir -p "$(dirname "$destination")"
    git clone --depth 1 "$url" "$destination"
fi
