from fastapi import FastAPI

from app.api.routes import context

app = FastAPI(title="AI Context Hub API")

app.include_router(context.router, prefix="/api", tags=["context"])
