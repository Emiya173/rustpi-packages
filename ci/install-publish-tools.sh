#!/usr/bin/env bash
set -Eeuo pipefail
[[ $EUID == 0 ]]
apt-get update
# Ubuntu splits vercmp and the libraries used by repo-add into makepkg.
apt-get install --yes --no-install-recommends pacman-package-manager makepkg libarchive-tools gnupg zstd
command -v repo-add vercmp bsdtar gpg
repo-add --version
