
from fastapi import FastAPI

from app.api.runs import router as runs_router

app = FastAPI(
    title="Durable AI Agent Runtime",
    version="0.1.0",
)


@app.get("/")
def root():
    return {
        "message": "Durable Agent Runtime is running"
    }


app.include_router(runs_router)
