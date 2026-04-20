import logging
import uuid
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from backend.logging_config import configure_logging, safe_log
from backend.config import get_settings
from backend.tools.schema_inspector import get_schema_context
from backend.workflows.graph import run_analysis
from backend.conversation.store import conversation_store

configure_logging()
logger = logging.getLogger(__name__)

settings = get_settings()

# ── Rate limiter ──────────────────────────────────────────────────────────────
limiter = Limiter(key_func=get_remote_address, default_limits=[settings.rate_limit])


# ── Lifespan ──────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("startup: loading schema context")
    app.state.schema_context = await get_schema_context()
    logger.info("startup: ready")
    yield
    logger.info("shutdown")


# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="Autonomous SQL Data Analyst Agent",
    version="3.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # restrict before public deployment
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type"],
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


@app.exception_handler(Exception)
async def _generic_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error("unhandled_exception", extra={"path": request.url.path, "error": str(exc)[:200]})
    return JSONResponse(
        status_code=500,
        content={"detail": "An internal error occurred. Please try again."},
    )


# ── Schemas ───────────────────────────────────────────────────────────────────
class AnalysisRequest(BaseModel):
    question: str
    session_id: str = ""     # empty = start new session


class StepResultResponse(BaseModel):
    step: str
    sql: str
    results: list[dict]
    error: str


class AnalysisResponse(BaseModel):
    session_id: str
    question: str
    plan: str
    plan_steps: list[str]
    step_results: list[StepResultResponse]
    insight: str
    confidence_score: float
    confidence_label: str
    error_message: str
    retry_count: int
    total_retries: int


class ConversationTurnResponse(BaseModel):
    question: str
    plan: str
    insight: str
    confidence_label: str


class ConversationHistoryResponse(BaseModel):
    session_id: str
    history: list[ConversationTurnResponse]


def _sanitize_error(error: str) -> str:
    if not error:
        return ""
    if error.startswith(("Only SELECT", "Multiple", "Max retries", "No SQL")):
        return error
    return "This step could not be completed. See the insight for details."


# ── Routes ────────────────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    return {"status": "ok", "version": app.version}


@app.get("/schema")
async def schema():
    return {"schema": app.state.schema_context}


@app.get("/conversation/{session_id}", response_model=ConversationHistoryResponse)
async def get_conversation(session_id: str):
    turns = conversation_store.get_turns(session_id)
    return ConversationHistoryResponse(
        session_id=session_id,
        history=[
            ConversationTurnResponse(
                question=t["question"],
                plan=t["plan"],
                insight=t["insight"],
                confidence_label=t["confidence_label"],
            )
            for t in turns
        ],
    )


@app.delete("/conversation/{session_id}")
async def clear_conversation(session_id: str):
    conversation_store.clear(session_id)
    logger.info("conversation_cleared", extra={"session_id": session_id})
    return {"status": "cleared", "session_id": session_id}


@app.post("/analyze", response_model=AnalysisResponse)
@limiter.limit(settings.rate_limit)
async def analyze(request: Request, body: AnalysisRequest):
    question = body.question.strip()

    if not question:
        raise HTTPException(status_code=400, detail="Question cannot be empty.")
    if len(question) > settings.max_question_length:
        raise HTTPException(
            status_code=400,
            detail=f"Question exceeds {settings.max_question_length} characters.",
        )

    # Resolve session: use provided ID or create a new one
    session_id = body.session_id.strip() or str(uuid.uuid4())
    conversation_history = conversation_store.format_for_prompt(session_id)

    logger.info(
        "analyze_request",
        extra={"question": safe_log(question), "session_id": session_id},
    )

    final_state = await run_analysis(
        question=question,
        schema_context=request.app.state.schema_context,
        conversation_history=conversation_history,
    )

    # Persist this turn to conversation history
    conversation_store.append(
        session_id=session_id,
        question=question,
        plan=final_state["plan"],
        insight=final_state["insight"],
        confidence_label=final_state.get("confidence_label", "None"),
    )

    return AnalysisResponse(
        session_id=session_id,
        question=final_state["question"],
        plan=final_state["plan"],
        plan_steps=final_state["plan_steps"],
        step_results=[
            StepResultResponse(
                step=sr["step"],
                sql=sr["sql"],
                results=sr["results"],
                error=_sanitize_error(sr["error"]),
            )
            for sr in final_state.get("step_results", [])
        ],
        insight=final_state["insight"],
        confidence_score=final_state.get("confidence_score", 0.0),
        confidence_label=final_state.get("confidence_label", "None"),
        error_message=_sanitize_error(final_state.get("error_message", "")),
        retry_count=final_state["retry_count"],
        total_retries=final_state.get("total_retries", 0),
    )
