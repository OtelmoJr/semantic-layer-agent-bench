FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_SYSTEM_PYTHON=1
RUN apt-get update && apt-get install -y --no-install-recommends make git && rm -rf /var/lib/apt/lists/* \
 && pip install --no-cache-dir uv

WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN uv pip install --system -e ".[dev]"
COPY . .

# Inside the container the venv paths in the Makefile point at the system interpreter.
ENV PY=python SLAB=slab DBT=dbt
ENTRYPOINT ["make"]
CMD ["smoke"]
