"""Full VOD manifests, bounded batches; no filesystem or network dependencies."""
import math
from pathlib import Path

SEGMENT_SECONDS = 4
BATCH_SEGMENTS = 4


def segment_count(duration):
    return math.ceil(duration / SEGMENT_SECONDS)


def media_playlist(duration, profile_index, token):
    lines = ["#EXTM3U", "#EXT-X-VERSION:3", "#EXT-X-TARGETDURATION:4", "#EXT-X-MEDIA-SEQUENCE:0",
             "#EXT-X-PLAYLIST-TYPE:VOD", "#EXT-X-INDEPENDENT-SEGMENTS"]
    for index in range(segment_count(duration)):
        if index and index % BATCH_SEGMENTS == 0:
            # Each batch is a separate encoder invocation with its own audio priming.
            lines.append("#EXT-X-DISCONTINUITY")
        length = min(SEGMENT_SECONDS, duration - index * SEGMENT_SECONDS)
        lines.extend([f"#EXTINF:{length:.6f},", f"v{profile_index}segment{index:06d}.ts?st={token}"])
    return "\n".join([*lines, "#EXT-X-ENDLIST", ""])


def master_playlist(options, token):
    lines = ["#EXTM3U", "#EXT-X-VERSION:3", "#EXT-X-INDEPENDENT-SEGMENTS"]
    for index, width, height, bitrate in options:
        lines.extend([f"#EXT-X-STREAM-INF:BANDWIDTH={math.ceil((bitrate + 192000) * 1.1)},RESOLUTION={width}x{height}",
                      f"variant{index}.m3u8?st={token}"])
    return "\n".join([*lines, ""])


def batch_command(command, folder, profile_index, first_segment, duration):
    """Convert a hardware single-rendition command into a finite, aligned HLS batch."""
    command = list(command)
    # Do not pace VOD: generate only this small requested range as fast as possible.
    index = command.index("-readrate")
    del command[index:index + 2]
    command[command.index("-ss") + 1] = str(first_segment * SEGMENT_SECONDS)
    # Pad the final decoded frame before CFR conversion; -t still trims exactly
    # to the requested interval (24 fps otherwise loses one tail frame).
    command[command.index("-vf") + 1] += ",tpad=stop_mode=clone:stop_duration=0.1,fps=fps=30:start_time=0"
    command = command[:command.index("-f")]
    clip = min(BATCH_SEGMENTS * SEGMENT_SECONDS, duration - first_segment * SEGMENT_SECONDS)
    command += ["-r", "30", "-g", "120", "-t", str(clip),
                "-output_ts_offset", str(first_segment * SEGMENT_SECONDS), "-avoid_negative_ts", "disabled",
                "-f", "hls", "-hls_time", "4", "-hls_list_size", "0", "-start_number", str(first_segment),
                "-hls_flags", "temp_file+independent_segments",
                "-hls_segment_options", "mpegts_copyts=1:avoid_negative_ts=disabled",
                "-hls_segment_filename", str(Path(folder) / f"v{profile_index}segment%06d.ts"),
                str(Path(folder) / f"batch{profile_index}.m3u8")]
    return command
