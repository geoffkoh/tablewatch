"""The HTTP adapter behind `tablewatch serve`: the web UI and a read-only `/api/v1`.

Internal, with no stability promise as Python; the contract is the HTTP API
and its OpenAPI document (`docs/api/openapi.json`). This package's own
`__init__` imports nothing, so FastAPI and uvicorn load only when `serve`
runs.
"""
