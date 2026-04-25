import requests
import json
import urllib3
import logging
import os
from .headless_auth import sync_login
from .auth_check import confirm_auth

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

GATEWAY_BASE_URL = os.environ.get('IBKR_GATEWAY_URL', 'https://localhost:5000/v1/api')


class RetryClient:

    def _ensure_authenticated(self):
        if confirm_auth().status_code >= 300:
            logger.warning("Session unauthenticated — re-authenticating via Playwright")
            result = sync_login()
            if result != "Login Successful":
                raise RuntimeError("IBKR re-authentication failed")

    def _request(self, method, url, **kwargs):
        kwargs.setdefault('verify', False)
        response = getattr(requests, method)(url=url, **kwargs)
        if response.status_code >= 300:
            self._ensure_authenticated()
            response = getattr(requests, method)(url=url, **kwargs)
        return response

    def get(self, url, verify=False):
        return self._request('get', url, verify=verify)

    def post(self, url, verify=False, json=None):
        return self._request('post', url, verify=verify, json=json)


class IBKRClient:

    def __init__(self):
        self._client = RetryClient()
        self.baseUrl = GATEWAY_BASE_URL
        self.account = os.environ.get('IBKR_ACCT_NUMBER', '')
        self.endpoint = f'/iserver/account/{self.account}/orders' if self.account else None

    def _get_conid_from_symbol(self):
        pass

    def buy(self, conid, quantity):
        data = {
            "orders": [{
                "conid": conid,
                "orderType": "MKT",
                "side": "BUY",
                "tif": "DAY",
                "quantity": quantity
            }]
        }
        resp = self._client.post(url=f"{self.baseUrl}{self.endpoint}", json=data)
        respData = resp.json()
        if 'id' in respData[0]:
            respData = self._continue_and_confirm_order(respData)
        return respData

    def sell(self, conid, quantity):
        data = {
            "orders": [{
                "conid": conid,
                "orderType": "MKT",
                "side": "SELL",
                "tif": "DAY",
                "quantity": quantity
            }]
        }
        resp = self._client.post(url=f"{self.baseUrl}{self.endpoint}", json=data)
        respData = resp.json()
        if 'id' in respData[0]:
            respData = self._continue_and_confirm_order(respData)
        return respData

    def stop_order(self, conid, quantity, stopPrice):
        data = {
            "orders": [{
                "conid": conid,
                "orderType": "STP",
                "price": stopPrice,
                "side": "BUY",
                "tif": "DAY",
                "quantity": quantity
            }]
        }
        resp = self._client.post(url=f"{self.baseUrl}{self.endpoint}", json=data)
        if resp.status_code >= 300:
            return {"message": "Error: Stop Loss Request Failed"}
        respData = resp.json()
        if 'id' in respData[0]:
            respData = self._continue_and_confirm_order(respData)
        return respData

    def _continue_and_confirm_order(self, respData):
        confirmed = False
        safety = 0
        while not confirmed and safety < 10:
            respData = self._order_reply(respData[0]['id'])
            if 'id' not in respData[0]:
                confirmed = True
            safety += 1
        return respData

    def _order_reply(self, orderId):
        resp = self._client.post(
            f'{self.baseUrl}/iserver/reply/{orderId}',
            json={"confirmed": True}
        )
        return resp.json()

    def _flatten_contracts_from_companies(self, companiesList):
        all_contracts = []
        for company in companiesList:
            all_contracts.extend(company['contracts'])
        return all_contracts

    def _flatten_companies_from_symbols(self, symbolsDict):
        all_companies = []
        for symbol_data in symbolsDict.values():
            all_companies.extend(symbol_data)
        return all_companies

    def _filter_us_exchange_contracts(self, contracts):
        return [
            c['conid'] for c in contracts
            if c['isUS'] and c['exchange'] in ('NASDAQ', 'NYSE')
        ]

    def fetch_conid(self, symbol):
        try:
            resp = self._client.get(url=f"{self.baseUrl}/trsrv/stocks?symbols={symbol}")
            respData = resp.json()
            all_contracts = self._flatten_contracts_from_companies(respData[symbol])
            for contract in all_contracts:
                if contract['isUS'] and contract['exchange'] in ('NASDAQ', 'NYSE'):
                    return contract['conid']
        except Exception as e:
            logger.exception(f"fetch_conid('{symbol}') failed: {e}")
        return None

    def fetch_conids(self, symbols):
        symbols_str = ','.join(symbols)
        try:
            resp = self._client.get(url=f"{self.baseUrl}/trsrv/stocks?symbols={symbols_str}")
            respData = resp.json()
            allCompanies = self._flatten_companies_from_symbols(respData)
            allContracts = self._flatten_contracts_from_companies(allCompanies)
            return self._filter_us_exchange_contracts(allContracts)
        except Exception as e:
            logger.exception(f"fetch_conids({symbols}) failed: {e}")
        return None

    def fetch_positions(self):
        resp = self._client.get(f'{self.baseUrl}/portfolio/{self.account}/positions/0')
        return json.dumps(resp.json())

    def fetch_position(self, symbol):
        conid = self._get_conid_from_symbol(symbol)
        resp = self._client.get(f'{self.baseUrl}/portfolio/{self.account}/position/{conid}')
        return json.dumps(resp.json())

    def _summary(self):
        resp = self._client.get(f'{self.baseUrl}/portfolio/{self.account}/summary')
        return json.dumps(resp.json())

    def fetch_acct_balance(self):
        pass
