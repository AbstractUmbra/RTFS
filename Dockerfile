ARG PYTHON_BASE=3.12-slim

FROM python:${PYTHON_BASE} AS builder

# disable update check since we're "static" in an image
ENV PDM_CHECK_UPDATE=false
# install PDM
RUN pip install -U pdm

WORKDIR /project
COPY . /project/

RUN pdm install --check --prod --no-editable

FROM python:${PYTHON_BASE}

LABEL org.opencontainers.image.source=https://github.com/abstractumbra/rtfs
LABEL org.opencontainers.image.description="An RTFS tool"

# install latest git
RUN apt-get update -y \
    && apt-get install --no-install-recommends --no-install-suggests -y git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=builder /project/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"
COPY . /app/

CMD ["python", "-O", "run.py"]
