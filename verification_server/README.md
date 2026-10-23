# H.M. Grisen Verification Server

A simple API whose purpose is to receive OAuth2 callbacks, verify them and enter successful attemps into a database.

# Setup

1. Make a copy of the `.env.example` file and rename it to `.env`

2. Make sure all the fields are filled

You have two options to run the API:

### Option 1 - Docker (Recommended)

```
docker compose up
```

### Option 2 - Manual

0. Install [uv](https://docs.astral.sh/uv/getting-started/installation/). It installs the right Python version for you

1. Install dependencies

```
uv sync
```

2. Run

```
uv run uvicorn src.server:app --port 8001
```
