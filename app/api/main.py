from fastapi import FastAPI

from app.api.routers import health, routes

app = FastAPI(title="Urban Transit Reliability Monitor", version="0.1.0")

app.include_router(health.router)
app.include_router(routes.router)
