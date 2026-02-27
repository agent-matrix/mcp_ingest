from __future__ import annotations

import os


def get_matrixhub_token() -> str | None:
    """
    Non-destructive compatibility helper.
    Matrix-Hub now protects admin endpoints (install/remotes/ingest) with Bearer auth.
    Prefer MATRIX_HUB_TOKEN (ecosystem standard), then MATRIX_TOKEN, then API_TOKEN.
    """
    return (
        os.getenv("MATRIX_HUB_TOKEN")
        or os.getenv("MATRIX_TOKEN")
        or os.getenv("API_TOKEN")
        or None
    )
