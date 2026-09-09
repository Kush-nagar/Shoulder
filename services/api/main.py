from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel

from services.api.problems import install_problem_handlers
from services.api.routes import router
from services.api.video import router as video_router

app = FastAPI(title="Shoulder API", version="0.1.0", docs_url=None, redoc_url=None)
app.include_router(router)
app.include_router(video_router)
install_problem_handlers(app)


class Health(BaseModel):
    status: Literal["ok"] = "ok"


@app.get("/health", response_model=Health)
def health() -> Health:
    return Health()
