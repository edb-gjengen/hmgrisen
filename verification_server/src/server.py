import os

import aiohttp
import asyncpg
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi import Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

app = FastAPI()

# HTML templates to serve prettier feedback to the user
app.mount("/static", StaticFiles(directory="src/static"), name="static")
templates = Jinja2Templates(directory="src/templates")


load_dotenv()

GALTINN_API_URL = os.environ["GALTINN_API_URL"]
GALTIINN_CLIENT_ID = os.environ["GALTINN_CLIENT_ID"]
GALTINN_REDIRECT_URI = os.environ["GALTINN_REDIRECT_URI"]
GALTINN_AUTH_TOKEN = os.environ["GALTINN_AUTH_TOKEN"]


@app.on_event("startup")
async def startup():
    credentials = {
        "host": os.environ["DATABASE_HOST"],
        "database": os.environ["DATABASE_NAME"],
        "user": os.environ["DATABASE_USER"],
        "password": os.environ["DATABASE_PASSWORD"],
    }
    app.state.pool = await asyncpg.create_pool(**credentials)


@app.on_event("shutdown")
async def shutdown():
    await app.state.pool.close()


@app.get("/")
async def index():
    return "Hei du! Her skal ikke du drive å luske!"


@app.get("/callback")
async def callback(request: Request, code: str, state: str):
    # Claim the pending verification. Deleting it up front makes the state single use
    verification = await app.state.pool.fetchrow(
        """
        DELETE FROM galtinn_verification
        WHERE state = $1 AND expires > NOW()
        RETURNING discord_id, challenge
        """,
        state,
    )
    if not verification:
        return templates.TemplateResponse(
            "error.html",
            {
                "request": request,
                "message": "Denne lenken er utløpt eller ugyldig! Prøv igjen fra start!",
            },
            status_code=400,
        )

    # The challenge column holds the PKCE code verifier
    discord_id, code_verifier = list(verification.values())

    # Get auth_token from code
    payload = {
        "client_id": GALTIINN_CLIENT_ID,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": GALTINN_REDIRECT_URI,
        "code_verifier": code_verifier,
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(f"{GALTINN_API_URL}/oauth/token/", data=payload) as r:
            if r.status != 200:
                return templates.TemplateResponse(
                    "error.html",
                    {
                        "request": request,
                        "message": "Kunne ikke hente hente autentiseringsnøkkel fra Galtinn!",
                    },
                    status_code=400,
                )
            token_data = await r.json()

    # Get user info from galtinn
    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"{GALTINN_API_URL}/oauth/userinfo/",
            headers={"Authorization": f"Bearer {token_data['access_token']}"},
        ) as r:
            if r.status != 200:
                return templates.TemplateResponse(
                    "error.html",
                    {
                        "request": request,
                        "message": "Kunne ikke hente hente brukerinfo fra Galtinn!",
                    },
                    status_code=502,
                )
            user = await r.json()

    # Enter discord user into galtinn
    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{GALTINN_API_URL}/discordprofiles/",
            json={"discord_id": discord_id, "user": user["sub"]},
            headers={"Authorization": f"Token {GALTINN_AUTH_TOKEN}"},
        ) as r:
            if r.status != 200 and r.status != 201:
                return templates.TemplateResponse(
                    "error.html",
                    {
                        "request": request,
                        "message": "Klarte ikke å skrive Discord id til Galtinn!",
                    },
                    status_code=502,
                )

    # Notify bot that user is verified
    # NOTIFY does not accept query arguments, but pg_notify does
    await app.state.pool.execute("SELECT pg_notify('galtinn_auth_complete', $1)", f"{discord_id} {user['sub']}")

    return RedirectResponse(f"/success/{user['preferred_username']}", status_code=303)


@app.get("/success/{name}")
async def success(request: Request, name: str):
    return templates.TemplateResponse("success.html", {"request": request, "name": name})
