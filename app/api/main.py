from fastapi import FastAPI

from app.api.routers import alerts, health, performance, regions, routes, runs, system

app = FastAPI(title="Urban Transit Reliability Monitor", version="0.2.0")

app.include_router(health.router)
app.include_router(regions.router)
app.include_router(system.router)
app.include_router(performance.router)
app.include_router(routes.router)
app.include_router(alerts.router)
app.include_router(runs.router)
