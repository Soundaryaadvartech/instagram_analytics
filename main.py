from fastapi import FastAPI
from routers.routers import router
from database.database import Base, engine
from database.models import SocialMedia

app = FastAPI(title = "Instagram Insights")

app.include_router(router)
Base.metadata.create_all(bind = engine, tables = [SocialMedia.__table__])

# Base.metadata.create_all(bind = engine, tables = [SocialMedia.__table__, Posts.__table__, PostInsights.__table__])