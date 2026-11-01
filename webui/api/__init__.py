"""CallVerse web API (step 1): a thin FastAPI layer over the existing Python functions.

It never contains business logic. It imports functions from `callverse/` and returns their result as JSON.
See webui/README.md for how to run it, and webui/api/app.py for the routes.
"""
