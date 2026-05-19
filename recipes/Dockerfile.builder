# Noble builder image for per-dep packaging work.
#
# Used by scripts/dockerized-build to run scripts/build-dep-package
# inside a clean ubuntu:24.04 environment when iterating from a
# non-Linux dev host. The repo gets bind-mounted at /work; build
# artifacts land under /work/build/deps/ exactly as if the build had
# been native.
#
# The package set is a union of every Build-Depends across the
# pypi-sdist overlays under packages/<source>/ -- hatchling /
# hatch-vcs / poetry-core / pdm-backend / setuptools-scm / quilt /
# lintian -- plus the codec headers Pillow needs. Inflating one
# image is cheaper than apt-installing on every container start.

FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    LC_ALL=C.UTF-8 \
    LANG=C.UTF-8 \
    DEBFULLNAME="Avalan Packaging Team" \
    DEBEMAIL="avalan@avalan.ai"

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        curl \
        debhelper \
        devscripts \
        dh-python \
        dpkg-dev \
        fakeroot \
        git \
        libfreetype-dev \
        libjpeg-dev \
        liblcms2-dev \
        libopenjp2-7-dev \
        libtiff-dev \
        libwebp-dev \
        lintian \
        pybuild-plugin-pyproject \
        python3-all \
        python3-all-dev \
        python3-babel \
        flit \
        python3-hatch-fancy-pypi-readme \
        python3-hatch-vcs \
        python3-hatchling \
        python3-installer \
        python3-markupsafe \
        python3-numpy \
        python3-packaging \
        python3-pdm-backend \
        python3-pip \
        python3-poetry-core \
        python3-pretend \
        python3-pygments \
        python3-pytest \
        python3-setuptools \
        python3-setuptools-scm \
        python3-sphinx \
        quilt \
        wget \
        xz-utils \
        zlib1g-dev \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /work
