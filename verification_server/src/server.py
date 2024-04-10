import os

import aiohttp
import psycopg2
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


# DB
db_connection = psycopg2.connect(
    host=os.environ["DATABASE_HOST"],
    dbname=os.environ["DATABASE_NAME"],
    user=os.environ["DATABASE_USER"],
    password=os.environ["DATABASE_PASSWORD"],
)
db_connection.autocommit = True
db_cursor = db_connection.cursor()


@app.get("/")
async def index():
    return "Hei du! Her skal ikke du drive å luske!"


@app.get("/callback")
async def callback(request: Request, code: str, state: str):

    # Check if user is pending verification
    db_cursor.execute(
        """
        SELECT discord_id, challenge, state
        FROM galtinn_verification WHERE state = %s
        """,
        (state,),
    )
    if not (db_result := db_cursor.fetchone()):
        return templates.TemplateResponse(
            "error.html",
            {
                "request": request,
                "message": "Denne lenken er utløpt eller ugyldig! Prøv igjen fra start",
            },
        )

    discord_id, code_challenge, state = db_result

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
    db_cursor.execute(
        """
        INSERT INTO galtinn_users (discord_id, galtinn_id)
        VALUES (%s, %s)
        """,
        (discord_id, user["sub"]),  # TODO: use UUID?
    )

    # Delete verification entry
    db_cursor.execute(
        """
        DELETE FROM galtinn_verification
        WHERE discord_id = %s
        """,
        (discord_id,),
    )

    return RedirectResponse(f"/success/{user['preferred_username']}", status_code=303)


@app.get("/success/{name}")
async def success(request: Request, name: str):
    return templates.TemplateResponse("success.html", {"request": request, "name": name})
