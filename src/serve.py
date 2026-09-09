"""
FastAPI HTTP 服务，提供流式 SSE 接口给 Web UI

接口（多轮会话版）：
  GET    /health                          健康检查
  POST   /sessions                        创建新会话，返回 session_id
  GET    /sessions                        列出所有历史会话
  GET    /sessions/{sid}                  查看会话记忆（turns）
  DELETE /sessions/{sid}                  清空会话记忆
  POST   /sessions/{sid}/query/{mode}     流式 ReAct（mode=manual|fc）

使用方式：
  uvicorn serve:app --host 0.0.0.0 --port 8000
"""

import os
import sys
import json
import logging
import asyncio
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
sys.path.insert(0, str(Path(__file__).parent))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ── 预加载 FAISS（启动时执行一次）────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("预加载 FAISS 索引和 Embedding 模型...")
    from tools import _load_rag
    await asyncio.to_thread(_load_rag)
    logger.info("预加载完成，服务就绪")
    yield


app = FastAPI(title="ReAct Financial Agent", lifespan=lifespan)


# ── 请求/响应模型 ─────────────────────────────────────────────────────────────
class QueryRequest(BaseModel):
    question:  str
    max_steps: int = 10


class CreateSessionResponse(BaseModel):
    session_id: str


# ── SSE 流式生成器 ────────────────────────────────────────────────────────────
def _sse(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _stream_react(
    question: str,
    max_steps: int,
    mode: str,
    session_id: str,
):
    """
    同步生成器（react_run）在独立线程中逐步执行，
    每产出一步通过 asyncio.Queue 传递给异步 SSE 生成器，
    实现真正的边思考边推送。
    """
    if mode == "manual":
        from react_manual import run as react_run
    else:
        from react_function_calling import run as react_run

    from memory import ShortTermMemory
    memory = ShortTermMemory(session_id)

    queue: asyncio.Queue = asyncio.Queue()
    _SENTINEL = object()

    def _worker():
        try:
            for step_data in react_run(
                question,
                max_steps=max_steps,
                session_id=session_id,
                memory=memory,
            ):
                queue.put_nowait(step_data)
        finally:
            queue.put_nowait(_SENTINEL)

    yield _sse({"type": "start", "question": question, "mode": mode, "session_id": session_id})

    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, _worker)

    while True:
        step_data = await queue.get()
        if step_data is _SENTINEL:
            break
        yield _sse(step_data)

    # 流结束再推一份最新记忆摘要，方便前端刷新侧栏
    yield _sse({
        "type":        "memory_snapshot",
        "session_id":  session_id,
        "turn_count":  len(memory.turns),
        "last_turn":   memory.last_turn.to_dict() if memory.last_turn else None,
    })
    yield _sse({"type": "done"})


# ── 路由：会话管理 ────────────────────────────────────────────────────────────
@app.post("/sessions", response_model=CreateSessionResponse)
async def create_session():
    """创建新会话，返回 session_id（前端保存到 localStorage）"""
    from memory import ShortTermMemory
    sid = f"sess_{uuid.uuid4().hex[:10]}"
    ShortTermMemory(sid)   # 初始化空文件
    return {"session_id": sid}


@app.get("/sessions")
async def list_sessions():
    """列出所有历史会话（按修改时间倒序）"""
    from memory import MEMORY_DIR
    sessions = []
    for p in MEMORY_DIR.glob("*.json"):
        try:
            stat = p.stat()
            with open(p, encoding="utf-8") as f:
                data = json.load(f)
            sessions.append({
                "session_id": data.get("session_id", p.stem),
                "updated_at": data.get("updated_at", stat.st_mtime),
                "turn_count": len(data.get("turns", [])),
            })
        except Exception:
            continue
    sessions.sort(key=lambda x: x.get("updated_at", 0), reverse=True)
    return {"sessions": sessions}


@app.get("/sessions/{session_id}")
async def get_session(session_id: str):
    """获取会话的完整记忆内容"""
    from memory import ShortTermMemory
    mem = ShortTermMemory(session_id)
    if not mem.turns and not mem.path.exists():
        raise HTTPException(status_code=404, detail="会话不存在")
    return {
        "session_id": session_id,
        "turns":      [t.to_dict() for t in mem.turns],
    }


@app.delete("/sessions/{session_id}")
async def clear_session(session_id: str):
    """清空指定会话的所有 turn"""
    from memory import ShortTermMemory
    mem = ShortTermMemory(session_id)
    mem.turns = []
    mem.save()
    return {"status": "cleared", "session_id": session_id}


# ── 路由：流式 ReAct ─────────────────────────────────────────────────────────
@app.post("/sessions/{session_id}/query/manual")
async def query_manual(session_id: str, req: QueryRequest):
    return StreamingResponse(
        _stream_react(req.question, req.max_steps, "manual", session_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/sessions/{session_id}/query/fc")
async def query_fc(session_id: str, req: QueryRequest):
    return StreamingResponse(
        _stream_react(req.question, req.max_steps, "fc", session_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/health")
async def health():
    return {"status": "ok", "model": os.getenv("AGENT_MODEL", "qwen-max")}


# ── 托管 index.html ──────────────────────────────────────────────────────────
HTML_PATH = Path(__file__).parent.parent / "index.html"

@app.get("/")
async def root():
    if HTML_PATH.exists():
        return HTMLResponse(HTML_PATH.read_text(encoding="utf-8"))
    return HTMLResponse("<h2>index.html not found</h2>")
