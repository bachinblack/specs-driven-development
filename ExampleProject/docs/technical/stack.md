# Stack

- Mobile app: React Native, styled with Tailwind (NativeWind).
- Backend: Symfony (PHP), REST API consumed by the app.
- Database: PostgreSQL, schema in `docs/technical/database/schema.sql` (diagram in `docs/technical/database/schema.md`).

## Architecture

- The app only displays data and calls the API: business rules (ordering, filtering, validation) are implemented in the backend.
- Backend: controllers (API routes) → services (business logic) → repositories (Doctrine) and connectors (external services, see `docs/technical/dependencies/`).

## Test layers

Tests are organised by layer, and tagged with the rule they prove (see `specs-driven-development.md`).

- `tests/unit/`: PHPUnit, pure logic (services). App components are tested with Jest under `app/tests/unit/`.
- `tests/functional/`: PHPUnit, API routes called through the Symfony kernel, connectors replaced by fakes.
- `tests/integration/`: PHPUnit, repositories against a real database and real connectors.

Unit and functional tests never call real services.

## Commands

- `composer help`: lists the available commands (tests, lint, run).
- `composer test`: runs the full suite. `composer test -- --group PL-008` runs the tests of one rule.
- `tag-ls`, `tag-lookup`, `tag-check`: find and check the rules, see `CLAUDE.md`.
