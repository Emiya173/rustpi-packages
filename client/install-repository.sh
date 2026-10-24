#!/usr/bin/env bash
# Enable this repository on the existing ALARM installation without upgrading
# the kernel, restarting applications, or refreshing other repository databases.
set -Eeuo pipefail
[[ $EUID == 0 && $(uname -m) == aarch64 ]] || exit 1
src=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
state=/var/lib/emiya-rustpi-repository
expected=936E1ED81F1B219DA3F4D2260BBC591DA9D66626
server=https://github.com/Emiya173/rustpi-packages/releases/latest/download
[[ -f $src/emiya-rustpi.asc ]]
fingerprint=$(gpg --batch --show-keys --with-colons "$src/emiya-rustpi.asc" | awk -F: '$1=="fpr" {print $10; exit}')
[[ $fingerprint == "$expected" ]]
[[ ! -e /var/lib/pacman/db.lck ]]
install -d -m 755 "$state" "$state/validation-db" "$state/cache"
if [[ ! -e $state/validation-db/local ]]; then
    ln -s /var/lib/pacman/local "$state/validation-db/local"
fi
[[ $(readlink "$state/validation-db/local") == /var/lib/pacman/local ]]
if [[ ! -e $state/pacman.conf.before ]]; then
    install -m 600 /etc/pacman.conf "$state/pacman.conf.before"
fi
pacman-key --add "$src/emiya-rustpi.asc"
pacman-key --lsign-key "$expected"
cat > "$state/validation.conf" <<CONF
[options]
Architecture = aarch64
DBPath = $state/validation-db
CacheDir = $state/cache
GPGDir = /etc/pacman.d/gnupg
LogFile = /var/log/emiya-rustpi-repository.log
SigLevel = Required
[emiya-rustpi]
Server = $server
CONF
# This refresh is deliberately isolated from /var/lib/pacman: it verifies the
# repository signature without putting the system into a partial-upgrade state.
pacman --config "$state/validation.conf" -Sy --noconfirm
pacman --config "$state/validation.conf" -Sl emiya-rustpi > "$state/packages.txt"
python - "$state/packages.txt" <<'PY'
from pathlib import Path
import sys
names={line.split()[1] for line in Path(sys.argv[1]).read_text().splitlines()}
assert names == {'linux-aarch64-emiya-rustpi', 'linux-aarch64-emiya-rustpi-headers',
                 'linux-aarch64-emiya-rustpi-rknpu', 'ffmpeg',
                 'jellyfin-ffmpeg-system-rustpi', 'emiya-rustpi-keyring'}, names
PY
url=$(pacman --config "$state/validation.conf" -Sp --print-format '%l' emiya-rustpi-keyring)
[[ $url == "$server/emiya-rustpi-keyring-"*.pkg.tar.zst ]]
curl -fL --retry 3 -o "$state/keyring.pkg.tar.zst" "$url"
curl -fL --retry 3 -o "$state/keyring.pkg.tar.zst.sig" "$url.sig"
pacman-key --verify "$state/keyring.pkg.tar.zst.sig" "$state/keyring.pkg.tar.zst"
pacman -U --needed --noconfirm "$state/keyring.pkg.tar.zst"
cat > "$state/repository.conf" <<CONF
[emiya-rustpi]
SigLevel = Required
Server = $server
CONF
python - "$state/pacman.conf.new" <<'PY'
from pathlib import Path
import sys
text=Path('/etc/pacman.conf').read_text()
include='Include = /etc/pacman.d/emiya-rustpi.conf'
if include not in text:
    assert '[emiya-rustpi]' not in text, 'Existing manually configured repo; inspect before changing'
    assert text.count('[core]') == 1
    text=text.replace('[core]', include+'\n\n[core]', 1)
else:
    assert text.count(include)==1 and text.index(include)<text.index('[core]')
Path(sys.argv[1]).write_text(text)
PY
install -m 644 "$state/repository.conf" /etc/pacman.d/emiya-rustpi.conf
install -m 644 "$state/pacman.conf.new" /etc/pacman.conf
install -d -m 755 /var/lib/pacman/sync
install -m 644 "$state/validation-db/sync/emiya-rustpi.db" /var/lib/pacman/sync/emiya-rustpi.db
if [[ -f $state/validation-db/sync/emiya-rustpi.db.sig ]]; then
    install -m 644 "$state/validation-db/sync/emiya-rustpi.db.sig" /var/lib/pacman/sync/emiya-rustpi.db.sig
fi
[[ $(pacman-conf --repo-list | sed -n '1p') == emiya-rustpi ]]
pacman -Sl emiya-rustpi
date -Is > "$state/COMPLETE"
echo 'EMIYA RUSTPI REPOSITORY ENABLED'
echo 'Use paru (or sudo pacman -Syu) for full upgrades. No kernel or application was upgraded by this script.'
