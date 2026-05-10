from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from investbrief.web.routers import auth, data, watchlist, chat, preferences, email


def create_app() -> FastAPI:
    app = FastAPI(title="Invest Brief API", version="0.1.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(auth.router)
    app.include_router(data.router)
    app.include_router(watchlist.router)
    app.include_router(chat.router)
    app.include_router(preferences.router)
    app.include_router(email.router)

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    return app
