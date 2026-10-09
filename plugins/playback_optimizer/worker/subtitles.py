"""Bounded subtitle rendering helpers. No attachment filenames become paths."""
from pathlib import Path
import subprocess

TEXT_CODECS = {'ass', 'ssa', 'subrip', 'srt', 'mov_text', 'webvtt', 'text'}
BITMAP_CODECS = {'hdmv_pgs_subtitle', 'dvd_subtitle', 'dvb_subtitle'}
FONT_TYPES = {'application/x-truetype-font', 'application/vnd.ms-opentype', 'font/ttf', 'font/otf', 'application/x-font-ttf', 'application/x-font-otf'}


def selected_track(streams):
    tracks = [s for s in streams if s.get('codec_type') == 'subtitle']
    if not tracks:
        return None
    return max(tracks, key=lambda s: (bool(s.get('disposition', {}).get('default')), bool(s.get('disposition', {}).get('forced'))))


def font_arguments(streams, folder):
    attachments = [s for s in streams if s.get('codec_type') == 'attachment']
    fonts = []
    total = 0
    for ordinal, stream in enumerate(attachments):
        if stream.get('tags', {}).get('mimetype', '').lower() not in FONT_TYPES:
            continue
        size = int(stream.get('extradata_size') or 0)
        total += size
        if len(fonts) // 2 >= 16 or size > 8 * 1024 * 1024 or total > 32 * 1024 * 1024:
            raise ValueError('Embedded fonts exceed limits')
        # Use only our filenames, never a filename supplied by the container.
        fonts.extend([f'-dump_attachment:t:{ordinal}', str(Path(folder) / f'font{ordinal}.ttf')])
    return fonts


def extract_fonts(source, headers, streams, folder, run=subprocess.run):
    args = font_arguments(streams, folder)
    if not args:
        return
    run(['ffmpeg', '-v', 'error', '-nostdin', '-y', '-max_alloc', '16777216',
         *args, '-rw_timeout', '15000000', '-headers', headers,
         '-format_whitelist', 'mov,matroska,webm,mpegts,avi,flv',
         '-protocol_whitelist', 'http,https,tcp,tls,crypto', '-i', source,
         '-map', '0:v:0', '-c', 'copy', '-t', '0', '-f', 'null', '-'],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=25, check=True)


def extract_batch(source, headers, stream, folder, start, end, run=subprocess.run):
    target = Path(folder) / 'subtitles.ass'
    # Preserve absolute ASS event times and effects. Seek before the requested
    # batch to retain events crossing its start; never demux a whole rendition.
    preroll = max(0, start - 60)
    run(['ffmpeg', '-v', 'error', '-nostdin', '-y', '-max_alloc', '16777216',
         '-copyts', '-ss', str(preroll), '-rw_timeout', '15000000', '-headers', headers,
         '-format_whitelist', 'mov,matroska,webm,mpegts,avi,flv',
         '-protocol_whitelist', 'http,https,tcp,tls,crypto', '-i', source,
         '-map', f'0:{int(stream["index"])}', '-vn', '-an', '-to', str(end),
         '-c:s', 'copy' if stream.get('codec_name') in {'ass', 'ssa'} else 'ass',
         '-fs', '4194304', '-f', 'ass', str(target)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=25, check=True)
    if not target.is_file() or target.stat().st_size >= 4194304:
        raise ValueError('Subtitle extraction exceeds limits')
    return target


def burn_filter(filter_graph, folder, start):
    # Session paths are server-owned UUIDs, not user/provider filenames.
    folder = Path(folder).as_posix()
    if any(c in folder for c in "':,;[]\\"):
        raise ValueError('Unsafe subtitle cache path')
    return (filter_graph + ',hwdownload,format=nv12,'
            f'setpts=PTS+{start}/TB,ass=filename={folder}/subtitles.ass:fontsdir={folder},'
            f'setpts=PTS-{start}/TB,format=nv12,hwupload')


def burn_bitmap(command, stream_index, size):
    command = list(command)
    # Sparse bitmap packets must be read independently. Sharing the video
    # demuxer makes overlay wait for subtitles while queuing full video frames;
    # a sought 4K HDR batch can exhaust the container before producing any TS.
    source = command[command.index('-i') + 1]
    subtitle_input = []
    for option in ('-rw_timeout', '-format_whitelist', '-protocol_whitelist', '-headers', '-ss'):
        subtitle_input.extend([option, command[command.index(option) + 1]])
    subtitle_input.extend(['-vn', '-an', '-i', source])
    index = command.index('-map')
    command[index:index] = subtitle_input
    index = command.index('-vf')
    graph = command[index + 1]
    command[index:index + 2] = ['-filter_complex',
        graph + ',hwdownload,format=nv12[video];'
        f'[1:{int(stream_index)}]scale=w={size[0]}:h={size[1]}[subs];'
        '[video][subs]overlay=eof_action=pass:shortest=0,format=nv12,hwupload[burned]']
    index = command.index('-map') + 1
    assert command[index] == '0:v:0'
    command[index] = '[burned]'
    return command
