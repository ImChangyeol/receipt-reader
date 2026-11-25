"""Start the app: python run.py  (then open http://localhost:8000)"""

import os
import threading
import time
import webbrowser

import uvicorn

from app.server import app

if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    if not os.getenv("NO_BROWSER"):
        threading.Thread(target=lambda: (time.sleep(1.5), webbrowser.open(f"http://localhost:{port}")),
                         daemon=True).start()
    # 127.0.0.1 only: the app is not reachable from other computers.
    uvicorn.run(app, host="127.0.0.1", port=port)
