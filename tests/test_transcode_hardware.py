from pathlib import Path
from unittest.mock import Mock

import pytest

from transcoder.hardware import HardwareDetector


def mapped_gpu(tmp_path, vendor, name='renderD129'):
    device = tmp_path / 'dev' / name
    device.parent.mkdir()
    device.touch()
    sys = tmp_path / 'sys' / name / 'device'
    sys.mkdir(parents=True)
    (sys / 'vendor').write_text(vendor)
    return HardwareDetector(device.parent, tmp_path / 'sys'), device


@pytest.mark.parametrize('vendor,driver', [('0x8086', 'iHD'), ('0x1002', 'radeonsi')])
def test_selects_actual_mapped_node_and_vendor_driver(tmp_path, monkeypatch, vendor, driver):
    detector, device = mapped_gpu(tmp_path, vendor)
    run = Mock(return_value=Mock(returncode=0, stdout=b'VAProfileH264High : VAEntrypointEncSliceLP\nVAProfileAV1Profile0 : VAEntrypointVLD'))
    monkeypatch.setattr('transcoder.hardware.subprocess.run', run)
    result = detector.probe()
    assert result['available'] and result['device'] == str(device)
    assert result['decodeCodecs'] == ['av1'] and result['driver'] == driver
    assert run.call_args.args[0][-1] == str(device)
    assert run.call_args.kwargs['env']['LIBVA_DRIVER_NAME'] == driver
    if vendor == '0x8086':
        assert run.call_args.kwargs['env']['LD_LIBRARY_PATH'].startswith('/opt/intel-modern/')
    else:
        assert 'LD_LIBRARY_PATH' not in run.call_args.kwargs['env']
    detector.probe()
    assert run.call_count == 1


def test_device_presence_does_not_hide_failed_driver_init(tmp_path, monkeypatch):
    detector, device = mapped_gpu(tmp_path, '0x8086')
    monkeypatch.setattr('transcoder.hardware.subprocess.run', Mock(return_value=Mock(returncode=1, stdout=b'')))
    assert not detector.probe()['available']
    assert 'failed' in detector.report['reason']


def test_decode_only_gpu_is_not_advertised_as_transcoder(tmp_path, monkeypatch):
    detector, device = mapped_gpu(tmp_path, '0x1002')
    monkeypatch.setattr('transcoder.hardware.subprocess.run', Mock(return_value=Mock(returncode=0, stdout=b'VAProfileAV1Profile0 : VAEntrypointVLD')))
    assert not detector.probe()['available']


def test_unsupported_vendor_never_runs_a_guessed_backend(tmp_path, monkeypatch):
    detector, device = mapped_gpu(tmp_path, '0x10de')
    run = Mock()
    monkeypatch.setattr('transcoder.hardware.subprocess.run', run)
    assert not detector.probe()['available']
    run.assert_not_called()
