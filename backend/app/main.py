"""CRM 主入口：初始化、路由注册、静态托管"""
import os
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from app.database import engine, Base, SessionLocal
from app import seed as seed_mod
from app.migrate import ensure_columns
from app.routers import (
    auth, base, leads, customers, sales, finance, service, analytics, system,
)

app = FastAPI(title="公司CRM系统", version="2.0")

for r in (auth, base, leads, customers, sales, finance, service, analytics, system):
    app.include_router(r.router)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")


@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)
    try:
        ensure_columns()   # 老库平滑补字段
    except Exception as exc:  # noqa
        print("[startup] 迁移警告:", exc)
    db = SessionLocal()
    try:
        seed_mod.seed(db)
    finally:
        db.close()


if os.path.isdir(STATIC_DIR):
    app.mount("/assets", StaticFiles(directory=os.path.join(STATIC_DIR, "assets")), name="assets")


@app.get("/api/health")
def health():
    return {"status": "ok", "version": "2.0"}


@app.get("/{full_path:path}")
def spa(full_path: str):
    """SPA 回退：非 /api 路径返回 index.html"""
    if full_path.startswith("api"):
        return {"detail": "Not Found"}
    index = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index):
        return FileResponse(index)
    return {"detail": "前端未构建", "hint": "请将前端文件放入 backend/app/static/"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=False)
