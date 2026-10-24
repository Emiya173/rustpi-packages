#!/usr/bin/env bash
# Native ARM64 ALARM build root on an ephemeral GitHub runner; no Docker.
set -Eeuo pipefail
[[ $(uname -m) == aarch64 ]]
[[ $EUID == 0 ]]
repo=$(realpath "${1:?repository directory}")
root=${2:-/opt/rustpi-alarm}
[[ ! -e $root ]]
mkdir -p "$root" /tmp/rustpi-bootstrap
cd /tmp/rustpi-bootstrap
curl --fail --location --retry 5 -o alarm.tar.gz https://os.archlinuxarm.org/os/ArchLinuxARM-aarch64-latest.tar.gz
curl --fail --location --retry 5 -o alarm.tar.gz.sig https://os.archlinuxarm.org/os/ArchLinuxARM-aarch64-latest.tar.gz.sig
gpg --batch --yes --dearmor -o alarm.gpg "$repo/keys/archlinuxarm.asc"
gpgv --keyring "$PWD/alarm.gpg" alarm.tar.gz.sig alarm.tar.gz
tar --numeric-owner --xattrs --acls -xpf alarm.tar.gz -C "$root"
rm -f alarm.tar.gz alarm.tar.gz.sig
mount --rbind /dev "$root/dev"
mount --make-rslave "$root/dev"
mount -t proc proc "$root/proc"
mount --rbind /sys "$root/sys"
mount --make-rslave "$root/sys"
install -m 644 /etc/resolv.conf "$root/etc/resolv.conf"
# The build root contains only ALARM repositories. It never consumes the custom
# binary repository it is building, nor any local rustpi packages or services.
# shellcheck disable=SC2016 # These variables are expanded later by pacman.
printf 'Server = https://mirror.archlinuxarm.org/$arch/$repo\n' > "$root/etc/pacman.d/mirrorlist"
chroot "$root" pacman-key --init
chroot "$root" pacman-key --populate archlinuxarm
chroot "$root" pacman -Sy --noconfirm archlinuxarm-keyring
chroot "$root" pacman -Syu --noconfirm --needed base-devel git python gnupg cmake ninja meson curl
mkdir -p "$root/build"
cp -a "$repo/." "$root/build/"
chroot "$root" useradd --create-home --uid 2000 builder
chroot "$root" chown -R builder:builder /build
printf 'builder ALL=(ALL) NOPASSWD: /usr/bin/pacman\n' > "$root/etc/sudoers.d/rustpi-builder"
chmod 440 "$root/etc/sudoers.d/rustpi-builder"
# Native builds avoid cross-tool binaries and Nix runtime paths in headers.
cat >> "$root/etc/makepkg.conf" <<'CONF'
MAKEFLAGS="-j4"
PACKAGER='Emiya rustpi CI <rustpi-packages@users.noreply.github.com>'
PKGEXT='.pkg.tar.zst'
COMPRESSZST=(zstd -c -T2 -10)
OPTIONS=(!strip docs libtool staticlibs emptydirs zipman purge !debug !lto !autodeps)
CONF
chroot "$root" runuser -u builder -- gpg --batch --import /build/keys/ffmpeg-devel.asc /build/keys/ffmpeg-tag-signer.asc
