from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel

from services.api.demo_routes import router as demo_router
from services.api.judgment_routes import router as judgment_router
from services.api.observation_routes import router as observation_router
from services.api.practice_routes import router as practice_router
from services.api.problems import install_problem_handlers
from services.api.publication_routes import router as publication_router
from services.api.reflection_routes import router as reflection_router
from services.api.retention_routes import router as retention_router
from services.api.routes import router
from services.api.tracking_routes import router as tracking_router
from services.api.video import router as video_router

app = FastAPI(title="Shoulder API", version="0.1.0", docs_url=None, redoc_url=None)
app.include_router(router)
app.include_router(video_router)
app.include_router(observation_router)
app.include_router(judgment_router)
app.include_router(publication_router)
app.include_router(reflection_router)
app.include_router(retention_router)
app.include_router(practice_router)
app.include_router(tracking_router)
app.include_router(demo_router)
install_problem_handlers(app)


class Health(BaseModel):
    status: Literal["ok"] = "ok"


@app.get("/health", response_model=Health)
def health() -> Health:
    return Health()
