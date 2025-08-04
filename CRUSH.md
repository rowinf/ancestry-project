## Ancestry Project: AI-Assisted Coding Rules

This document outlines the conventions and commands for AI agents working on this project.

### Commands

- **Run the application:** `quart run`
- **Install dependencies:** `uv pip install -r requirements.txt` (or `pip install -r requirements.txt`)

*There are currently no automated tests, linters, or formatters.*

### Code Style

- **Imports:** Group imports as follows: standard library, third-party libraries, then project-specific modules. Sort them alphabetically.
- **Formatting:** Adhere to PEP 8 standards. Use a maximum line length of 100 characters.
- **Types:** Use type hints for all function signatures.
- **Naming:**
    - Use `snake_case` for variables and functions.
    - Use `PascalCase` for classes.
    - Use `UPPER_SNAKE_CASE` for constants.
- **Error Handling:**
    - Raise specific exceptions (`ValueError`, `TypeError`) instead of generic `Exception`.
    - Use `try...except` blocks for code that may raise exceptions, such as API calls or file I/O.
    - Use `flash()` to display user-facing error messages.
- **Security:**
    - Never hardcode secrets. Use `os.getenv()` to load them from environment variables.
    - Ensure `SECRET_KEY` is set.
- **Templates:** Use `render_template()` to render HTML templates from the `templates` directory.
- **Datastar:**
    - Use `DatastarResponse` for server-sent events.
    - Use `SSE.patch_elements()` to update the DOM.
- **State Management:** Use the `session` object to store user-specific data.
