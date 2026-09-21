from __future__ import annotations

import os

import uvicorn

from assure_control_api.app import create_app

app = create_app()


def main() -> None:
    uvicorn.run(
        "assure_control_api.main:app",
        host=os.environ.get("API_HOST", "127.0.0.1"),
        port=int(os.environ.get("API_PORT", "8000")),
        reload=False,
    )


if __name__ == "__main__":
    main()
