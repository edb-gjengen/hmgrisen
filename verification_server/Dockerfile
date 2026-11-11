FROM python:3.14

COPY --from=ghcr.io/astral-sh/uv:0.13.5 /uv /uvx /bin/

WORKDIR /app

# The bot's uid (bot/Dockerfile)
RUN useradd --system --uid 935 --home-dir /app --no-create-home hmgrisen

ENV UV_COMPILE_BYTECODE=1 UV_NO_CACHE=1 UV_PYTHON_DOWNLOADS=never

COPY pyproject.toml uv.lock ./

RUN uv sync --locked --no-dev

COPY . .

ENV PATH="/app/.venv/bin:$PATH"

USER hmgrisen

CMD [ "uvicorn", "src.server:app", "--host", "0.0.0.0", "--port", "8001" ]
