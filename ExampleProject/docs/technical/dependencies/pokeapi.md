---
features: NP
---

# PokeAPI

Official doc: https://pokeapi.co/docs/v2

## Usage

Fetches the information of an official pokemon (type, description) to pre-fill the new pokemon form (@NP-006).

- Direction: out (HTTPS, read only).
- Endpoints: `GET /api/v2/pokemon/{name}` (types), `GET /api/v2/pokemon-species/{name}` (description, in `flavor_text_entries`).

## Authentication and limits

- No authentication.
- No hard quota, but fair use is expected: responses must be cached on our side.

## Connector

`PokeApiClient`, not developed yet: it comes with the first rule that needs it (@NP-006), along with a fake used by the unit and functional tests.
