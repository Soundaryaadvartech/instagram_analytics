from fastapi import FastAPI
from routers.routers import router

app = FastAPI(title = "Instagram Insights")

app.include_router(router)