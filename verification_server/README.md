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

0. Install Python 3.12+

1. Install dependencies

```
pip install -r requirements.txt -U
```

2. Run - See [this guide](https://fastapi.tiangolo.com/#create-it)
