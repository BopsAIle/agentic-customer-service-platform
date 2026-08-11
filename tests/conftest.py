from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main import app
from app.models import Customer, Order, SupportTicket
from app.models.entities import OrderStatus, TicketStatus


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    with testing_session.begin() as session:
        session.add_all(
            [
                Customer(id=1, name="Test Customer", email="test@example.com"),
                Customer(id=2, name="Other Customer", email="other@example.com"),
            ]
        )
        session.add_all(
            [
                Order(id=1, customer_id=1, status=OrderStatus.SHIPPED, total_amount="25.00"),
                Order(id=2, customer_id=1, status=OrderStatus.DELIVERED, total_amount="30.00"),
                Order(id=3, customer_id=1, status=OrderStatus.PENDING, total_amount="35.00"),
                Order(id=4, customer_id=1, status=OrderStatus.PROCESSING, total_amount="40.00"),
                Order(id=5, customer_id=2, status=OrderStatus.DELIVERED, total_amount="45.00"),
            ]
        )
        session.add_all(
            [
                SupportTicket(
                    id=1,
                    customer_id=1,
                    order_id=1,
                    category="delivery",
                    status=TicketStatus.OPEN,
                    description="Where is my order?",
                ),
                SupportTicket(
                    id=2,
                    customer_id=2,
                    order_id=5,
                    category="billing",
                    status=TicketStatus.OPEN,
                    description="I have a question.",
                ),
            ]
        )
    with testing_session() as session:
        yield session
    Base.metadata.drop_all(engine)


@pytest.fixture
def client(db_session: Session) -> Generator[TestClient, None, None]:
    def override_get_db() -> Generator[Session, None, None]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
