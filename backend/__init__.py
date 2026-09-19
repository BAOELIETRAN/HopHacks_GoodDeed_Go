"""GoodDeed Go -- backend layer (FastAPI + SQLite).

Data, auth, leaderboard/tier logic, and HTTP glue around the AI agent in
``gooddeed_agent``. This package does not implement scoring or discovery
itself -- it calls into ``gooddeed_agent`` (see ``agent_client.py``), which
already runs against deterministic mock data with zero API keys, so this
backend is developable end-to-end before real keys exist.
"""
