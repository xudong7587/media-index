"""Run actual HLS mux/seek reference checks with software codecs, never NAS/115.

Usage: PYTHONPATH=backend:. python scripts/validate_transcode_vod.py --ffmpeg /path/to/ffmpeg
This deliberately substitutes software decode/encode. It does NOT validate VAAPI.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess
import tempfile

from transcoder.app import encode_command
from transcoder.vod import batch_command, media_playlist


def reference_command(command, binary):
    command = list(command)
    command[0] = binary
    for option in ("-init_hw_device", "-hwaccel", "-hwaccel_output_format", "-headers"):
        index = command.index(option)
        del command[index:index + 2]
    command[command.index("-protocol_whitelist") + 1] += ",file"
    index = command.index("-vf") + 1
    size = re.search(r"w=(\d+):h=(\d+)", command[index])
    suffix = command[index].split(":format=nv12", 1)[1]
    command[index] = f"scale={size[1]}:{size[2]},format=yuv420p" + suffix
    command[command.index("h264_vaapi")] = "libx264"
    command[command.index("-profile:v"):command.index("-profile:v")] = ["-preset", "ultrafast"]
    return command


def run(command):
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=40)
    if result.returncode:
        raise RuntimeError(result.stderr.decode(errors="replace"))
    return result.stdout.decode(errors="replace")


def frame_positions(binary, path):
    result = run([binary, "-v", "error", "-copyts", "-protocol_whitelist", "file,crypto,data", "-i", str(path),
                  "-map", "0:v:0", "-fps_mode", "passthrough", "-f", "framemd5", "-"])
    return [int(line.split(",")[2]) for line in result.splitlines() if line and not line.startswith("#")]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ffmpeg", required=True)
    parser.add_argument("--source-rate", default="30")
    args = parser.parse_args()
    binary = args.ffmpeg
    with tempfile.TemporaryDirectory(prefix="mediaindex-vod-reference-") as temporary:
        folder = Path(temporary)
        source = folder / "source.mp4"
        run([binary, "-v", "error", "-f", "lavfi", "-i", f"testsrc2=size=320x180:rate={args.source_rate}",
             "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000", "-t", "32.5",
             "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-movflags", "+faststart", str(source)])
        lengths = []
        for first in (0, 4, 8):
            command = encode_command(str(source), "unused", folder, (320,180), 8000000, 0, "h264")
            command = batch_command(command, folder, 2, first, 32.5)
            run(reference_command(command, binary))
            lengths.extend(float(x) for x in re.findall(r"#EXTINF:([\d.]+)", (folder / "batch2.m3u8").read_text()))
        assert lengths == [4.0] * 8 + [.5], lengths
        starts = {}
        for number in (0, 3, 4, 7, 8):
            frames = frame_positions(binary, folder / f"v2segment{number:06d}.ts")
            starts[number] = frames[0]
            assert len(frames) == (15 if number == 8 else 120), (number, len(frames))
        assert all(value == starts[0] + number * 120 for number, value in starts.items()), starts
        playlist = re.sub(r"\?st=[^\n]+", "", media_playlist(32.5,2,"reference"))
        (folder / "vod.m3u8").write_text(playlist)
        decoded = frame_positions(binary, folder / "vod.m3u8")
        assert len(decoded) == 975, len(decoded)
        audio = subprocess.run([binary, "-v", "error", "-protocol_whitelist", "file,crypto,data", "-i", str(folder / "vod.m3u8"),
            "-map", "0:a:0", "-ac", "1", "-ar", "48000", "-f", "s16le", "-"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=40, check=True)
        audio_seconds = len(audio.stdout) / 2 / 48000
        assert abs(audio_seconds - 32.5) < .15, audio_seconds
        print(json.dumps({"checks": "software HLS reference only", "segments": len(lengths), "videoFrames": len(decoded),
                          "audioSeconds": audio_seconds, "batchStarts": starts, "sourceRate": args.source_rate, "vaapiValidated": False}))


if __name__ == "__main__":
    main()
