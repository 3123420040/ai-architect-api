FROM ubuntu:24.04

ARG DEBIAN_FRONTEND=noninteractive
ARG NODE_MAJOR=22
ARG BLENDER_VERSION=4.5.1
ARG KTX_VERSION=4.4.2

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/workspace \
    BLENDER_BIN=/opt/blender/blender \
    KTX_BIN=/usr/bin/ktx \
    GLTF_TRANSFORM_BIN=/workspace/tools/sprint2/node_modules/.bin/gltf-transform \
    PATH=/opt/blender:/workspace/tools/sprint2/node_modules/.bin:$PATH

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        gnupg \
        xz-utils \
        python3.12 \
        python3.12-venv \
        python3-pip \
        make \
        git \
        ffmpeg \
        libdbus-1-3 \
        libegl1 \
        libfontconfig1 \
        libglib2.0-0 \
        libgl1 \
        libice6 \
        libsm6 \
        libx11-6 \
        libx11-xcb1 \
        libxext6 \
        libxi6 \
        libxkbcommon0 \
        libxrender1 \
        libxxf86vm1 \
    && curl -fsSL https://deb.nodesource.com/setup_${NODE_MAJOR}.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && curl -fsSL https://download.blender.org/release/Blender4.5/blender-${BLENDER_VERSION}-linux-x64.tar.xz -o /tmp/blender.tar.xz \
    && mkdir -p /opt/blender \
    && tar -xf /tmp/blender.tar.xz -C /opt/blender --strip-components=1 \
    && curl -fsSL https://github.com/KhronosGroup/KTX-Software/releases/download/v${KTX_VERSION}/KTX-Software-${KTX_VERSION}-Linux-x86_64.deb -o /tmp/ktx.deb \
    && apt-get install -y /tmp/ktx.deb || dpkg -i /tmp/ktx.deb || true \
    && apt-get install -f -y \
    && rm -rf /var/lib/apt/lists/* /tmp/blender.tar.xz /tmp/ktx.deb

RUN ln -sf /usr/bin/python3.12 /usr/local/bin/python

WORKDIR /workspace

CMD ["bash"]
