# Scopelines artifact: Spot 2.15.1 built from source, plus the Python
# dependencies and the artifact itself.
#
#   docker build -t scopelines .
#   docker run --rm -it --user "$(id -u):$(id -g)" -v "$PWD/results:/scopelines/results" scopelines

# ---------------- Spot, built from source ----------------
FROM ubuntu:24.04 AS spot-builder

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential wget ca-certificates python3 python3-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /tmp
RUN wget -q https://www.lre.epita.fr/dload/spot/spot-2.15.1.tar.gz \
    && tar xzf spot-2.15.1.tar.gz
WORKDIR /tmp/spot-2.15.1
RUN ./configure --prefix=/usr/local --disable-devel \
    && make -j"$(nproc)" \
    && make install

# ---------------- Runtime image ----------------
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/usr/local/lib/python3.12/site-packages \
    LD_LIBRARY_PATH=/usr/local/lib \
    MPLCONFIGDIR=/tmp/matplotlib

# fonts-liberation provides the sans-serif font the figures are rendered with
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 python3-pip libgomp1 libcairo2 fontconfig fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

COPY --from=spot-builder /usr/local /usr/local
RUN ldconfig

WORKDIR /scopelines
COPY requirements.txt .
RUN pip3 install --break-system-packages -r requirements.txt

COPY . .
# writable by any user, as the image is meant to run with --user (the host user)
RUN mkdir -p results && chmod -R a+rwX /scopelines

# Fails the build if Spot, cairo, or the search does not work
RUN python3 -c "import spot, buddy, cairosvg; print('Spot', spot.version())" \
    && python3 find_scopeline.py 'G(a -> F b)' --svg /tmp/check.svg \
    && rm -f /tmp/check.svg

CMD ["/bin/bash"]
