"""Local preview and container API; the Vercel frontend proxies these endpoints."""

from __future__ import annotations

import asyncio
import hmac
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .chat import ChatRequest, Retriever, answer_events, event, settings


def create_app(retriever=None, answer_client=None) -> FastAPI:
    retriever = retriever or Retriever()
    slots = asyncio.Semaphore(4)

    @asynccontextmanager
    async def lifespan(app):
        try:
            await asyncio.to_thread(retriever.start)
        except Exception as error:
            logging.getLogger(__name__).warning(
                "Retrieval startup failed: %s", type(error).__name__
            )
        yield
        retriever.close()

    app = FastAPI(title="Code.Hub Assistant", version="0.2.0", lifespan=lifespan)

    def authorized(request: Request):
        token = settings().get("RAG_API_TOKEN")
        if token and not hmac.compare_digest(
            request.headers.get("authorization", ""), f"Bearer {token}"
        ):
            raise HTTPException(401, "Unauthorized")

    @app.get("/health")
    def health():
        return {"status": "ok" if retriever.status()["ready"] else "degraded"}

    @app.get("/api/status", dependencies=[Depends(authorized)])
    def status():
        return retriever.status()

    @app.post("/api/chat", dependencies=[Depends(authorized)])
    async def chat(payload: ChatRequest, request: Request):
        async def stream():
            async with slots:
                yield event("stage", {"stage": "searching"})
                try:
                    sources, _, elapsed = await asyncio.to_thread(retriever.search, payload)
                except ValueError:
                    yield event(
                        "error",
                        {
                            "code": "query_invalid",
                            "message": "Η ερώτηση είναι πολύ μεγάλη. Δοκίμασε πιο σύντομα.",
                        },
                    )
                    return
                except Exception as error:
                    logging.getLogger(__name__).warning(
                        "Retrieval failed: %s", type(error).__name__
                    )
                    yield event(
                        "error",
                        {
                            "code": "retrieval_unavailable",
                            "message": "Η αναζήτηση δεν είναι διαθέσιμη. Δοκίμασε ξανά.",
                        },
                    )
                    return
                yield event("sources", {"sources": sources, "retrieval_ms": round(elapsed)})
                if await request.is_disconnected():
                    return
                yield event("stage", {"stage": "answering"})
                try:
                    async for part in answer_events(payload, sources, settings(), answer_client):
                        if await request.is_disconnected():
                            return
                        yield part
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    logging.getLogger(__name__).warning("Answer failed: %s", type(error).__name__)
                    yield event(
                        "error",
                        {
                            "code": "answer_unavailable",
                            "message": "Δεν ολοκληρώθηκε η απάντηση. Δοκίμασε ξανά.",
                        },
                    )

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "X-Accel-Buffering": "no",
                "X-Content-Type-Options": "nosniff",
            },
        )

    bundled_web = Path(__file__).parent / "web"
    default_web = (
        bundled_web
        if bundled_web.exists()
        else Path(__file__).resolve().parents[2] / "web" / "public"
    )
    web = Path(settings().get("RAG_WEB_ROOT", str(default_web)))
    if web.exists():

        @app.get("/")
        def index():
            return FileResponse(web / "index.html")

        app.mount("/", StaticFiles(directory=web), name="web")
    return app


app = create_app()
