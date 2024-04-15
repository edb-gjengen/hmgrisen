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
    # Check if user is pending verification
    verification = await app.state.pool.fetchrow(
        """
        SELECT discord_id, challenge, state
        FROM galtinn_verification WHERE state = $1
        """,
        state,
    )
    if not verification:
        return templates.TemplateResponse(
            "error.html",
            {
                "request": request,
                "message": "Denne lenken er utløpt eller ugyldig! Prøv igjen fra start",
            },
        )

    discord_id, code_challenge, state = list(verification.values())

    # Get auth_token from code
    payload = {
        "client_id": GALTIINN_CLIENT_ID,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": GALTINN_REDIRECT_URI,
        "code_verifier": code_challenge,
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(f"{GALTINN_API_URL}/oauth/token/", data=payload) as r:
            if r.status != 200:
                return templates.TemplateResponse(
                    "error.html",
                    {
                        "request": request,
                        "message": "Kunne ikke hente hente nøkkel fra Galtinn. Kontakt din nærmeste EDB'er",
                    },
                )
            token_data = await r.json()
            print(token_data)

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
                        "message": "Kunne ikke hente hente brukerinfo fra Galtinn. Kontakt din nærmeste EDB'er",
                    },
                )
            user = await r.json()

    # Enter user into database

    # Delete verification entry
    await app.state.pool.execute(
        """
        DELETE FROM galtinn_verification
        WHERE discord_id = $1
        """,
        discord_id,
    )

    # Notify bot that user is verified
    # asyncpg does not allow for arguments in NOTIFY queries, hence we use f-strings
    notify_query = f"NOTIFY galtinn_auth_complete, '{discord_id} {user['sub']}'"
    await app.state.pool.execute(notify_query)

    return RedirectResponse(f"/success/{user['preferred_username']}", status_code=303)


@app.get("/success/{name}")
async def success(request: Request, name: str):
    return templates.TemplateResponse("success.html", {"request": request, "name": name})
