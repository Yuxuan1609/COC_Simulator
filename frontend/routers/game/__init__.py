"""frontend/routers/game — 游戏 API 包（URL 不变，无 re-export）。"""
from fastapi import APIRouter

from . import session, turn, combat, charcard, slash, views, debug

router = APIRouter(tags=["game"])
router.include_router(session.router)
router.include_router(turn.router)
router.include_router(combat.router)
router.include_router(charcard.router)
router.include_router(slash.router)
router.include_router(views.router)
router.include_router(debug.router)
