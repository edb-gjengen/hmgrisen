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
    try:
        discord_id, _ = state.split(":")
    except ValueError:
        return templates.TemplateResponse(
            "error.html",
            {
                "request": request,
                "message": "Ugyldig forespørsel! Manglende data eller feil format",
            },
        )

    # Check if user is pending verification
    db_cursor.execute(
        """
        SELECT *
        FROM verification WHERE discord_id = %s
        """,
        (discord_id,),
    )
    if not (db_result := db_cursor.fetchone()):
        return templates.TemplateResponse(
            "error.html",
            {
                "request": request,
                "message": "Denne lenken er utløpt eller ugyldig! Prøv igjen fra start",
            },
        )

    if db_result[1] != state:
        return templates.TemplateResponse(
            "error.html",
            {
                "request": request,
                "message": "Ugyldig lenke! Prøv igjen fra start",
            },
        )

    # Get auth_token from code
    payload = {
        "client_id": GALTIINN_CLIENT_ID,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": GALTINN_REDIRECT_URI,
        "code_verifier": state,
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(f"{GALTINN_API_URL}/ouath/token/", data=payload) as r:
            if r.status != 200:
                return templates.TemplateResponse(
                    "error.html",
                    {
                        "request": request,
                        "message": "Kunne ikke hente hente nøkkel fra Galtinn. Kontakt din nærmeste EDB'er",
                    },
                )
            data = await r.json()
            print(data)

    # Get user info from galtinn
    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"{GALTINN_API_URL}/oauth/userinfo/",
            headers={"Authorization": f"Bearer {data['access_token']}"},
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
        INSERT INTO users (discord_id, galtinn_id)
        VALUES (%s, %s)
        """,
        (discord_id, user["id"]),
    )

    # Delete verification entry
    db_cursor.execute(
        """
        DELETE FROM verification WHERE discord_id = %s
        """,
        (discord_id,),
    )

    return RedirectResponse(f"/success/{user['name']}", status_code=303)


@app.get("/success/{name}")
async def success(request: Request, name: str):
    return templates.TemplateResponse("success.html", {"request": request, "name": name})
