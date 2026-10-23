FROM python:3.14

COPY --from=ghcr.io/astral-sh/uv:0.13.5 /uv /uvx /bin/

WORKDIR /app

RUN apt-get update && apt-get install -y pandoc

ENV UV_COMPILE_BYTECODE=1 UV_NO_CACHE=1 UV_PYTHON_DOWNLOADS=never

COPY pyproject.toml uv.lock ./

RUN uv sync --locked --no-dev

COPY . .

ENV PATH="/app/.venv/bin:$PATH"

VOLUME logs

CMD ["python3", "src/run.py"]
