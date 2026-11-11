# One image for both: the bot is its default command, and the verification server runs from
# the same image with its own working directory and command (docker-compose.yml)
FROM python:3.14

COPY --from=ghcr.io/astral-sh/uv:0.13.5 /uv /uvx /bin/

RUN apt-get update && apt-get install -y pandoc

# The uid matches the account that owns the mounted directories on amiga (edb-infra,
# group_data/hmgrisen.py)
RUN useradd --system --uid 935 --home-dir /app --no-create-home hmgrisen

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 UV_NO_CACHE=1 UV_PYTHON_DOWNLOADS=never

COPY pyproject.toml uv.lock ./

RUN uv sync --locked --no-dev --no-install-project

COPY . .

ENV PATH="/app/.venv/bin:$PATH"

# Owned by the user, so a fresh volume is writable too
RUN mkdir -p /app/bot/logs && chown hmgrisen:hmgrisen /app/bot/logs

USER hmgrisen

# Both read their files relative to their own directory: ./src/cogs, ./src/static
WORKDIR /app/bot

VOLUME /app/bot/logs

CMD ["python3", "src/run.py"]
