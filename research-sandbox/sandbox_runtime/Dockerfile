FROM python:3.12-slim@sha256:2c941e860699f878900b0edc2403613c234d4b32eda3cc9fa7036991a2a63c4a

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/opt/sandbox_sdk

RUN groupadd --gid 10001 sandbox && useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin sandbox
WORKDIR /work
COPY requirements.lock /tmp/requirements.lock
RUN pip install --require-hashes -r /tmp/requirements.lock

ENV HOME=/tmp/home \
    XDG_CACHE_HOME=/tmp/cache \
    MPLCONFIGDIR=/tmp/matplotlib \
    OMP_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1 \
    MKL_NUM_THREADS=1 \
    NUMEXPR_NUM_THREADS=1 \
    VECLIB_MAXIMUM_THREADS=1 \
    BLIS_NUM_THREADS=1 \
    MALLOC_CONF=background_thread:false,narenas:1 \
    ARROW_DEFAULT_MEMORY_POOL=system

# Matplotlib otherwise builds its font cache on every run and starts a helper
# thread. The runtime seccomp profile deliberately denies clone syscalls, so
# build a sealed seed cache once. The trusted bootstrap copies this small cache
# into the per-run tmpfs before executing generated code.
RUN mkdir -p /opt/matplotlib-cache \
    && MPLCONFIGDIR=/opt/matplotlib-cache python -c "import matplotlib.pyplot as plt; plt.figure(); plt.close()" \
    && chown -R root:root /opt/matplotlib-cache \
    && chmod -R a-w /opt/matplotlib-cache
COPY sandbox_sdk /opt/sandbox_sdk/sandbox_sdk
COPY runtime_bootstrap.py /opt/runtime_bootstrap.py
RUN chown -R root:root /opt/sandbox_sdk && chmod -R a-w /opt/sandbox_sdk

USER 10001:10001
ENTRYPOINT ["python", "/opt/runtime_bootstrap.py"]
