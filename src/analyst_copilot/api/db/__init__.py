"""Postgres access for product state — chat history today, auth tomorrow.

The index artefacts stay on disk; this database holds rows: conversations,
messages and (eventually) users, provider settings and job records. A sync
engine with psycopg is deliberate: the QA pipeline is synchronous, and route
handlers run DB work in FastAPI's threadpool, so an async driver would buy
nothing and cost clarity.
"""
