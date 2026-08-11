import os
from collections.abc import Generator

os.environ.setdefault("CHECKPOINT_BACKEND", "memory")
os.environ.setdefault("RAG_BACKEND", "local")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.backends import StaticBearerAuthenticator
from app.auth.dependencies import get_authenticator
from app.auth.models import ActorType, Principal
from app.core.database import Base, get_db
from app.main import app
from app.models import Customer, Order, SupportTicket
from app.models.entities import OrderStatus, TicketStatus

TEST_OPERATOR_TOKEN = "test-operator-token"
TEST_CUSTOMER_ONE_TOKEN = "test-customer-one-token"
TEST_CUSTOMER_TWO_TOKEN = "test-customer-two-token"


def _test_authenticator() -> StaticBearerAuthenticator:
    return StaticBearerAuthenticator(
        {
            TEST_OPERATOR_TOKEN: Principal(
                actor_id="operator-test",
                actor_type=ActorType.SUPPORT_OPERATOR,
                roles=["support_operator"],
                credential_id="test-operator",
            ),
            TEST_CUSTOMER_ONE_TOKEN: Principal(
                actor_id="customer-test-1",
                actor_type=ActorType.CUSTOMER,
                roles=["customer"],
                customer_id=1,
                credential_id="test-customer-1",
            ),
            TEST_CUSTOMER_TWO_TOKEN: Principal(
                actor_id="customer-test-2",
                actor_type=ActorType.CUSTOMER,
                roles=["customer"],
                customer_id=2,
                credential_id="test-customer-2",
            ),
        }
    )


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
    app.dependency_overrides[get_authenticator] = _test_authenticator
    with TestClient(
        app,
        headers={"Authorization": f"Bearer {TEST_OPERATOR_TOKEN}"},
    ) as test_client:
        yield test_client
    app.dependency_overrides.clear()
