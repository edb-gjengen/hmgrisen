# H.M. Grisen

A multi-purpose Discord bot. Its main purpose is to link Galtinn users to their Discord accounts.

## Set up

This repo is meant as a monorepo for the Discord bot and the verification server. Thus we will only explain how to run them together as a unit here. See the respective folders' README files for instructions on how to run them individually.

1. Create a `.env` file in the root of the project. Use the `.env.example` file as a template.

2. Run `docker compose up`

## Database

The Docker Compose file does not specify the set up of a database. We assume you have a Postgres DB running with a user set up. The bot will create the necessary tables on its own.
