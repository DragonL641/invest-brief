from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from investbrief.web.routers import auth, data, stocks, chat, preferences, email


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    # Shutdown: clean up the data router's thread pool
    from investbrief.web.routers.data import _pool
    _pool.shutdown(wait=False)


def create_app() -> FastAPI:
    app = FastAPI(title="Invest Brief API", version="0.1.0", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(auth.router)
    app.include_router(data.router)
    app.include_router(stocks.router)
    app.include_router(chat.router)
    app.include_router(preferences.router)
    app.include_router(email.router)

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    return app
