from pathlib import Path

from transcoder import app as worker, hdr, vod, subtitles
from app.services import transcode as transport
import httpx
import pytest


def test_hdr_preserves_precision_then_maps_before_encoding_and_subtitles():
    for transfer in ('smpte2084', 'arib-std-b67'):
        command = worker.encode_command('http://source', '', Path('/cache/session'),
                                        (1280, 720), 2000000, 0, 'hevc', transfer)
        graph = command[command.index('-vf') + 1]
        assert graph.index('format=p010') < graph.index('t=linear') < graph.index('tonemap=') < graph.index('format=nv12')
        assert f'tin={transfer}' in graph
        assert 'sidedata=mode=delete:type=MASTERING_DISPLAY_METADATA' in graph
        assert command[command.index('-color_trc') + 1] == 'bt709'
        batch = vod.batch_command(command, Path('/cache/session'), 3, 16, 1000)
        burned = subtitles.burn_bitmap(batch, 6, (1280, 720))
        assert 'tonemap=' in burned[burned.index('-filter_complex') + 1]
        assert batch[batch.index('-ss') + 1] == '64'


def test_sdr_and_untrusted_transfer_never_inject_mapping():
    for transfer in ('', 'bt709', 'smpte2084,evil'):
        graph = hdr.scale_filter((1920, 1080), transfer)
        assert graph == 'scale_vaapi=w=1920:h=1080:format=nv12'
        assert hdr.output_options(transfer) == []


def test_adaptive_renditions_each_convert_hdr():
    command = worker.adaptive_command('http://source', '', Path('/cache/session'),
                                      3840, 2160, 0, True, 'hevc', 'smpte2084')
    assert command[command.index('-filter_complex') + 1].count('tonemap=tonemap=hable') == 4
    assert command[command.index('-color_trc') + 1] == 'bt709'


@pytest.mark.parametrize('detail,expected', [
    ('HDR tone mapping not yet supported', '当前转码器不支持此 HDR 视频，请使用原画'),
    ('https://secret.invalid?token=private', '转码请求未完成'),
    ({'token': 'private'}, '转码请求未完成'),
])
def test_known_failures_are_translated_without_exposing_worker_details(monkeypatch, detail, expected):
    monkeypatch.setattr(transport, 'worker_config', lambda: ('http://worker', 'k' * 32))
    class Client:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def request(self, *args, **kwargs): return httpx.Response(503, json={'detail': detail})
    monkeypatch.setattr(transport.httpx, 'Client', Client)
    with pytest.raises(transport.TranscodeError, match=expected):
        transport.call_worker('POST', '/sessions', payload={})
