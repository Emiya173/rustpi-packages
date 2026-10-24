#!/usr/bin/env bash
set -Eeuo pipefail
[[ $(uname -m) == aarch64 && $EUID != 0 ]]
cd /build
group=${1:?group}
mkdir -p out
case "$group" in
    kernel) recipes=(kernel);;
    ffmpeg) recipes=(ffmpeg);;
    integration) recipes=(jellyfin-adapter keyring);;
    *) exit 2;;
esac
for recipe in "${recipes[@]}"; do
    cd "/build/packages/$recipe"
    # Packaging-only integration recipes do not need their runtime dependencies
    # installed in the builder (the patched FFmpeg is built by another job).
    if [[ $group == integration ]]; then
        makepkg --nodeps --noconfirm --cleanbuild
    else
        makepkg --syncdeps --noconfirm --cleanbuild
    fi
    makepkg --printsrcinfo > /build/out/"$recipe".SRCINFO
    mapfile -t packages < <(makepkg --packagelist)
    for package in "${packages[@]}"; do
        # Epoch remains in .PKGINFO; artifact filenames must be portable.
        filename=$(basename "$package" | sed -E 's/-[0-9]+:/-/')
        cp "$package" "/build/out/$filename"
    done
done
cd /build
python ci/validate.py "$group" out
cp ci-plan.json sources.lock.json out/
echo "BUILD VALIDATED: $group"
