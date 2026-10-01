# run.py
import os

import uvicorn

if __name__ == "__main__":
    # Set RELOAD=false while converting to avoid mid-job server restarts (WatchFiles).
    reload = os.getenv("RELOAD", "true").lower() in ("1", "true", "yes")
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=reload,
    )