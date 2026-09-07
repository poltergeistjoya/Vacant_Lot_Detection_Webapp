#!/usr/bin/env python3
"""Run the FastAPI development server for the playground backend."""

import uvicorn

if __name__ == "__main__":
    uvicorn.run("server.app:app", host="127.0.0.1", port=8000, reload=True)
