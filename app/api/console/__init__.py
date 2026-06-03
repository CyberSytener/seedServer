from fastapi import APIRouter
from .modules import router as modules_router
from .flows import router as flows_router
from .providers import router as providers_router
from .runs import router as runs_router

def create_console_runtime_router():
    main_router = APIRouter(prefix="/v1", tags=["Console Runtime"])
    main_router.include_router(modules_router)
    main_router.include_router(flows_router)
    main_router.include_router(providers_router)
    main_router.include_router(runs_router)
    return main_router
