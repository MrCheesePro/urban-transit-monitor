from fastapi import FastAPI

from app.api.routers import health, performance, routes, system

app = FastAPI(title="Urban Transit Reliability Monitor", version="0.1.0")

app.include_router(health.router)
app.include_router(routes.router)
app.include_router(performance.router)
app.include_router(system.router)
