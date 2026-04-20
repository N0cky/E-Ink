# Contributing

Thanks for taking the time to contribute to PlexImageE-Ink.

## Development Setup

1. Create a virtual environment.
2. Install dependencies from `app/requirements.txt`.
3. Copy `.env.example` to `.env`.
4. Start the local dev server with `python app/server.py`.

## Project Structure

- `app/` contains the framework core
- `modules/` contains self-contained content modules
- `templates/` contains the web UI templates
- `tests/` contains the current smoke and unit tests
- `docs/modules.md` explains how to build a new module

## Before Opening a PR

Please make sure the following pass locally:

1. `python -m py_compile app/server.py app/module_base.py wsgi.py`
2. `python -m unittest tests.test_module_registry tests.test_settings_validation tests.test_gallery_data_source`
3. Template smoke test:

```bash
python -c "from app.server import app; [app.jinja_env.get_template(name) for name in ['base.html','index.html','settings.html','logs.html']]; print('TEMPLATES_OK')"
```

## Coding Notes

- Keep new features modular and prefer module hooks over server special cases.
- Avoid committing generated files, logs, caches, local secrets, or virtualenv contents.
- If you add a new module, also update `docs/modules.md` and `.env.example` when relevant.
- If behavior changes are user-facing, add a short note to `CHANGELOG.md`.

## Reporting Issues

When filing a bug report, include:

- what you expected
- what happened instead
- relevant log lines
- whether you are running locally or via Docker
- which module was active
