"""Start the API after initializing its persistent demo workspace."""
from contextlib import asynccontextmanager, closing
from collections.abc import AsyncIterator
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.concurrency import run_in_threadpool
from app.core.config import Settings
from app.core.database import connect
from app.core.seed import seed_database
from app.models.schema import create_tables
from app.routers.auth import router
from app.routers.records import router as records_router
from app.schemas.auth import HealthResponse, AdapterStatus


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create an independently configurable API instance."""
    config = settings or Settings()
    def initialize() -> None:
        """Finish schema and seed work before accepting requests."""
        with closing(connect(config.database_path)) as db:
            create_tables(db)
            if config.seed_on_startup:
                seed_database(db)
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        """Initialize storage before readiness."""
        await run_in_threadpool(initialize)
        yield
    app = FastAPI(title='Procurem API',version='1.0.0',description='Local procurement demo API',lifespan=lifespan)
    app.state.settings = config
    app.add_middleware(CORSMiddleware,allow_origins=config.origins,allow_credentials=True,allow_methods=['GET','POST','OPTIONS'],allow_headers=['Content-Type'])
    app.include_router(router)
    app.include_router(records_router)

    @app.get('/api/health',response_model=HealthResponse,tags=['Health'],summary='Check local adapter data')
    def health(request: Request) -> HealthResponse:
        """Report each local adapter as up only when its tables contain rows."""
        tables = {'Oracle':['purchase_orders','invoices','contracts','requisitions'],'JAGGAER':['suppliers','sourcing_events'],'Catalog':['catalog_items'],'Spend':['spend_monthly'],'Knowledge':['knowledge_docs']}
        with closing(connect(request.app.state.settings.database_path)) as db:
            adapters = [AdapterStatus(name=name,state='up' if all(db.execute(f'SELECT 1 FROM {table} LIMIT 1').fetchone() for table in names) else 'empty') for name,names in tables.items()]
        return HealthResponse(status='ok',adapters=adapters)
    return app

app = create_app()
