from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api.routes import router
import config

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)

@app.on_event("startup")
async def startup():
    # Load GTFS at startup (BE2 fills this in)
    pass

if __name__ == "__main__":
    import os
    import uvicorn
    # Local dev binds to localhost only; Railway runs `uvicorn main:app --host 0.0.0.0 --port $PORT`.
    uvicorn.run(app, host=os.getenv("HOST", "127.0.0.1"), port=config.PORT)
