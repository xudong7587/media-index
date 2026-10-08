FROM python:3.12-slim-trixie
WORKDIR /worker
# Wildcat Lake requires the newer Intel userspace stack. Keep the rest of the
# image on stable Debian; pin the driver and opt in only its graphics libraries.
ARG INTEL_MEDIA_DRIVER_VERSION=26.2.4+ds1-1
RUN sed -i 's/Components: main/Components: main contrib non-free non-free-firmware/' /etc/apt/sources.list.d/debian.sources \
    && echo 'deb http://deb.debian.org/debian sid main non-free' > /etc/apt/sources.list.d/intel-media.list \
    && printf 'Package: *\nPin: release a=unstable\nPin-Priority: 100\n' > /etc/apt/preferences.d/intel-media \
    && apt-get update \
    && apt-get install --no-install-recommends -y ffmpeg vainfo mesa-va-drivers fonts-noto-cjk \
    && mkdir /tmp/intel-packages /opt/intel-modern \
    && cd /tmp/intel-packages \
    && apt-get download intel-media-va-driver-non-free=${INTEL_MEDIA_DRIVER_VERSION} \
       libigdgmm12/sid libva2/sid libva-drm2/sid libdrm2/sid libdrm-intel1/sid libpciaccess0/sid \
    && for package in *.deb; do dpkg-deb -x "$package" /opt/intel-modern; done \
    && cd /worker && rm -rf /tmp/intel-packages \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY --chmod=644 app.py vod.py hardware.py subtitles.py ./
RUN chmod 644 app.py vod.py hardware.py && useradd --uid 10002 --no-create-home worker && mkdir /cache && chown worker /cache
USER worker
ENV TRANSCODE_CACHE_DIR=/cache
EXPOSE 8098
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8098", "--no-access-log"]
