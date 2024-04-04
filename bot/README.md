# H.M. Grisen

A multi-purpose Discord bot for the Discord server of The Norwegian Student Society

## Get started

0. Create a bot user / obtain a bot token. [Se her](https://discordpy.readthedocs.io/en/stable/discord.html)

1. Make a copy of the `.env.example` file and rename it to `.env`

2. Make sure all the fields are filled

Given a user with a access to a database the bot will create all the necessary tables by itself.

You have two options to run the bot:

### Option 1 - Docker (Recommended)

```
docker-compose up
```

### Option 2 - Manual

0. Install Python 3.12+

1. Install dependencies

```
pip install -r requirements.txt -U
```

2. Run bot

```
python src/run.py
```
