from __future__ import annotations

import os

import uvicorn

from assure_demo.app import create_app

app = create_app()


def main() -> None:
    uvicorn.run(
        "assure_demo.main:app",
        host=os.environ.get("DEMO_HOST", "127.0.0.1"),
        port=int(os.environ.get("DEMO_PORT", "8080")),
        reload=False,
    )


if __name__ == "__main__":
    main()
