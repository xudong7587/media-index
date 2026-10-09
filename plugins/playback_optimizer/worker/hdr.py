"""HDR-to-SDR conversion after hardware resize; no untrusted filter expressions."""
HDR_TRANSFERS = {'smpte2084', 'arib-std-b67'}


def needs_mapping(video):
    return video.get('color_transfer') in HDR_TRANSFERS


def scale_filter(size, transfer=''):
    width, height = size
    if transfer not in HDR_TRANSFERS:
        return f'scale_vaapi=w={width}:h={height}:format=nv12'
    # Resize before the CPU color transform, but keep 10-bit HDR samples until
    # conversion to linear float. Decode and H.264 encode still use the GPU.
    return (f'scale_vaapi=w={width}:h={height}:format=p010,hwdownload,format=p010le,'
            f'zscale=tin={transfer}:pin=bt2020:min=bt2020nc:t=linear:npl=100,'
            'format=gbrpf32le,zscale=p=bt709,tonemap=tonemap=hable:desat=0,'
            'zscale=t=bt709:m=bt709:r=tv,format=nv12,'
            'sidedata=mode=delete:type=MASTERING_DISPLAY_METADATA,'
            'sidedata=mode=delete:type=CONTENT_LIGHT_LEVEL,hwupload')


def output_options(transfer):
    return (['-color_primaries', 'bt709', '-color_trc', 'bt709', '-colorspace', 'bt709',
             '-color_range', 'tv'] if transfer in HDR_TRANSFERS else [])
