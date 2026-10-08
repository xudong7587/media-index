from pathlib import Path
import pytest
from transcoder import subtitles


def test_default_styled_track_keeps_provider_font_names_out_of_paths(tmp_path):
    streams = [
        {'index': 2, 'codec_type': 'subtitle', 'codec_name': 'subrip'},
        {'index': 3, 'codec_type': 'subtitle', 'codec_name': 'ass', 'disposition': {'default': 1}},
        {'index': 4, 'codec_type': 'attachment', 'extradata_size': 1024,
         'tags': {'filename': '../../secret.ttf', 'mimetype': 'application/x-truetype-font'}},
    ]
    assert subtitles.selected_track(streams)['index'] == 3
    args = subtitles.font_arguments(streams, tmp_path)
    assert args == ['-dump_attachment:t:0', str(tmp_path / 'font0.ttf')]
    assert '..' not in args[-1]
    streams[-1]['extradata_size'] = 9 * 1024 * 1024
    with pytest.raises(ValueError):
        subtitles.font_arguments(streams, tmp_path)


def test_seek_subtitle_extraction_preserves_absolute_timing_and_ass_effects(tmp_path):
    commands = []
    def run(command, **kwargs):
        commands.append(command)
        Path(command[-1]).write_text('[Events]\nDialogue: 0,0:02:00.00,0:02:04.00,Default,,0,0,0,,{\\fad(200,200)}Text')
    target = subtitles.extract_batch('http://gateway/source/token', 'private headers',
        {'index': 3, 'codec_name': 'ass'}, tmp_path, 128, 144, run=run)
    cmd = commands[0]
    assert '-copyts' in cmd
    assert cmd[cmd.index('-ss') + 1] == '68'
    assert cmd[cmd.index('-to') + 1] == '144'
    assert cmd[cmd.index('-c:s') + 1] == 'copy'
    assert '\\fad(200,200)' in target.read_text()
    graph = subtitles.burn_filter('scale_vaapi=w=1920:h=1080:format=nv12', Path('/cache/0123456789abcdef'), 128)
    assert graph.index('hwdownload') < graph.index('ass=filename=') < graph.index('hwupload')
    assert 'setpts=PTS+128/TB' in graph and 'setpts=PTS-128/TB' in graph


def test_renderer_rejects_unbounded_subtitle_and_filter_paths(tmp_path):
    def run(command, **kwargs):
        Path(command[-1]).write_bytes(b'x' * 4194304)
    with pytest.raises(ValueError):
        subtitles.extract_batch('source', '', {'index': 1, 'codec_name': 'ass'}, tmp_path, 0, 16, run=run)
    with pytest.raises(ValueError):
        subtitles.burn_filter('scale_vaapi', Path('/cache/provider:inject'), 0)


def test_pgs_overlay_keeps_hardware_encode_and_requested_output_dimensions():
    from transcoder.app import encode_command
    command = encode_command('source', '', Path('/cache/session'), (1920, 1080), 4000000, 1800000)
    command = subtitles.burn_bitmap(command, 2, (1920, 1080))
    assert '-vf' not in command
    graph = command[command.index('-filter_complex') + 1]
    assert '[0:2]scale=w=1920:h=1080[subs]' in graph
    assert 'overlay=eof_action=pass:shortest=0' in graph
    assert command[command.index('-map') + 1] == '[burned]'
    assert command[max(i for i, arg in enumerate(command) if arg == '-c:v') + 1] == 'h264_vaapi'
