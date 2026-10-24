Jellyfin + system FFmpeg on rustpi

This package is an argument adapter, not a separate FFmpeg build.
/usr/lib/jellyfin-ffmpeg/ffmpeg executes /usr/bin/ffmpeg.
The sibling ffprobe is a symlink to /usr/bin/ffprobe.

Requires the system FFmpeg build with V4L2 Request and NV15 download support.
Keep Jellyfin Hardware acceleration set to None and hardware encoding disabled.
H.264 8-bit / HEVC 8-10-bit / AV1 8-10-bit 4:2:0 local video transcodes to
libx264/libx265 use V4L2 Request decoding; filters and encoding use the CPU.
Direct play, stream copy and unsupported formats retain their original command.
Already selected hardware accelerators are not overridden.
The adapter logs [rustpi-v4l2-request] and actual FFmpeg device initialization.
An attempted hardware decoder failure is reported; it is not silently retried.
HDR tone mapping is not provided by this adapter.

The pacman provide jellyfin-ffmpeg satisfies jellyfin-server-bin dependencies
without installing another FFmpeg binary. Future upstream system FFmpeg updates
must retain the custom patches; the binary repository automation is pending.
