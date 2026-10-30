"""
Replays real PAPER fills through the order endpoints and checks that total_value counts
every open position (SiegeEngine holds two legs; ORB_Hydra scales into one short).
"""

import os
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))
os.environ.setdefault('DATABASE_URL', 'sqlite://')

from MultiStrategyAPI.api import orders
from MultiStrategyAPI.database import get_db
from MultiStrategyAPI.models import Base, PortfolioState, Position

INITIAL_CASH = 1000.0


@pytest.fixture
def sessionFactory():
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    # autoflush=False mirrors production (database.py), so the totals helper must flush itself
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    with factory() as db:
        for strategyName in ('SiegeEngine', 'ORB_Hydra'):
            db.add(PortfolioState(
                strategy_name=strategyName, cash=INITIAL_CASH, allocated_capital=INITIAL_CASH,
                initial_cash=INITIAL_CASH, total_value=INITIAL_CASH,
            ))
        db.commit()
    return factory


@pytest.fixture
def client(sessionFactory):
    app = FastAPI()
    app.include_router(orders.router)

    def override_get_db():
        with sessionFactory() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as testClient:
        yield testClient


def trade(client, endpoint: str, strategyName: str, symbol: str, price: float, quantity: int = None):
    response = client.post(f'/orders/{endpoint}', json={
        'strategy_name': strategyName, 'symbol': symbol, 'price': price, 'quantity': quantity,
    })
    assert response.status_code == 201, response.text


def portfolio_state(sessionFactory, strategyName: str) -> PortfolioState:
    with sessionFactory() as db:
        return db.query(PortfolioState).filter(PortfolioState.strategy_name == strategyName).one()


def test_two_leg_entry_keeps_total_value_at_entry_capital(client, sessionFactory):
    trade(client, 'buy_all', 'SiegeEngine', 'USO', 167.66, quantity=3)
    trade(client, 'sell_short_all', 'SiegeEngine', 'UCO', 66.565, quantity=5)

    state = portfolio_state(sessionFactory, 'SiegeEngine')
    assert state.cash == pytest.approx(164.195)
    assert state.collateral == pytest.approx(5 * 66.565)
    assert state.total_value == pytest.approx(INITIAL_CASH)
    assert state.total_return == pytest.approx(0)


def test_closing_one_leg_still_counts_the_other(client, sessionFactory):
    trade(client, 'buy_all', 'SiegeEngine', 'USO', 167.66, quantity=3)
    trade(client, 'sell_short_all', 'SiegeEngine', 'UCO', 66.565, quantity=5)
    trade(client, 'sell_all', 'SiegeEngine', 'USO', 170.00)

    state = portfolio_state(sessionFactory, 'SiegeEngine')
    usoGain = (170.00 - 167.66) * 3
    assert state.total_value == pytest.approx(INITIAL_CASH + usoGain)
    assert state.collateral == pytest.approx(5 * 66.565)

    trade(client, 'close_short_all', 'SiegeEngine', 'UCO', 64.00)

    state = portfolio_state(sessionFactory, 'SiegeEngine')
    ucoGain = (66.565 - 64.00) * 5
    assert state.cash == pytest.approx(INITIAL_CASH + usoGain + ucoGain)
    assert state.total_value == pytest.approx(state.cash)
    assert state.collateral == 0
    assert state.invested is False


def test_scaling_into_a_short_marks_total_value_to_last_fill(client, sessionFactory):
    hydraLegFills = [(1, 68.465), (1, 68.51), (2, 69.145), (1, 68.514), (3, 69.175), (4, 69.33)]
    shortShares, entryNotional = 0, 0.0
    for legShares, fillPrice in hydraLegFills:
        trade(client, 'sell_short_all', 'ORB_Hydra', 'TQQQ', fillPrice, quantity=legShares)
        shortShares += legShares
        entryNotional += legShares * fillPrice

        state = portfolio_state(sessionFactory, 'ORB_Hydra')
        unrealizedPnl = entryNotional - shortShares * fillPrice
        assert state.total_value == pytest.approx(INITIAL_CASH + unrealizedPnl)
        assert state.collateral == pytest.approx(entryNotional)

    trade(client, 'close_short_all', 'ORB_Hydra', 'TQQQ', 69.735)

    state = portfolio_state(sessionFactory, 'ORB_Hydra')
    assert state.cash == pytest.approx(INITIAL_CASH + entryNotional - shortShares * 69.735)
    assert state.cash == pytest.approx(991.80, abs=0.01)  # matches the PAPER row on 2026-10-29
    assert state.total_value == pytest.approx(state.cash)
    assert state.collateral == 0
    with sessionFactory() as db:
        assert db.query(Position).count() == 0


def test_short_over_orphaned_long_closes_long_without_phantom_short(client, sessionFactory, monkeypatch):
    executedTrades = []
    realPaperTrade = orders.execute_paper_trade
    monkeypatch.setattr(orders, 'execute_paper_trade', lambda *args: executedTrades.append(args) or realPaperTrade(*args))

    trade(client, 'buy_all', 'ORB_Hydra', 'TQQQ', 70.00, quantity=2)
    response = client.post('/orders/sell_short_all', json={
        'strategy_name': 'ORB_Hydra', 'symbol': 'TQQQ', 'price': 71.00, 'quantity': 3,
    })

    assert response.status_code == 409
    assert [args[0] for args in executedTrades] == ['BUY', 'SELL']  # the long's close only, no short sent
    state = portfolio_state(sessionFactory, 'ORB_Hydra')
    assert state.cash == pytest.approx(INITIAL_CASH + 2 * (71.00 - 70.00))
    assert state.total_value == pytest.approx(state.cash)
    with sessionFactory() as db:
        assert db.query(Position).count() == 0
        assert db.query(orders.Order).count() == 2


def test_total_return_pct_is_on_initial_capital_not_last_position(client, sessionFactory):
    trade(client, 'sell_short_all', 'ORB_Hydra', 'TQQQ', 68.34, quantity=7)
    trade(client, 'close_short_all', 'ORB_Hydra', 'TQQQ', 69.735)

    state = portfolio_state(sessionFactory, 'ORB_Hydra')
    totalReturn = 7 * (68.34 - 69.735)
    assert state.total_return == pytest.approx(totalReturn)
    assert state.total_return_pct == pytest.approx(totalReturn / INITIAL_CASH * 100)


def test_position_return_pct_measures_one_position():
    oneShareCost = 68.34
    assert orders.position_return_pct(68.34 - 69.735, oneShareCost) == pytest.approx(-2.0412, abs=1e-4)
    assert orders.position_return_pct(5.0, 0) == 0.0


def test_partial_short_close_counts_remaining_shares(client, sessionFactory):
    trade(client, 'sell_short_all', 'ORB_Hydra', 'TQQQ', 70.00, quantity=4)
    trade(client, 'close_short_all', 'ORB_Hydra', 'TQQQ', 69.00, quantity=1)

    state = portfolio_state(sessionFactory, 'ORB_Hydra')
    realizedGain = 1.00
    remainingUnrealized = 3 * (70.00 - 69.00)
    assert state.total_value == pytest.approx(INITIAL_CASH + realizedGain + remainingUnrealized)
    assert state.collateral == pytest.approx(3 * 70.00)
