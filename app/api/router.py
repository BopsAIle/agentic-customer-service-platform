from fastapi import APIRouter

from app.api.routes import agent, customers, escalations, health, memories, orders, tickets

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(customers.router)
api_router.include_router(orders.router)
api_router.include_router(tickets.router)
api_router.include_router(escalations.router)
api_router.include_router(agent.router)
api_router.include_router(memories.router)
