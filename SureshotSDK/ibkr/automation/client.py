import requests
import json
import urllib3
import logging
import os

# Ignore insecure error messages
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Get secrets from ENV or Vault

class IBKRClient:

    account = os.environ['IBKR_ACCT_NUMBER']
    baseUrl = 'https://localhost:5000/v1/api'
    endpoint = f'/iserver/account/{account}/orders'

    def __init__(self):
        pass

    def _get_conid_from_symbol(self):
        pass

    def buy(self,conid,quantity):

        data = {
            "orders":[{
                "conid": conid,
                "orderType": "MKT",
                "side": "BUY",
                "tif": "DAY",
                "quantity": quantity
            }]
        }

        resp = requests.post(url=f"{self.baseUrl}{self.endpoint}", verify=False, json=data)
        respJSON = json.dumps(resp.json())

        # If stale connection
        #   Reauthenticate()
        #   RepeatRequest()

        # If needs order_reply
        #   ibkr.order_reply(returned_id)

        return respJSON

    def sell(self,conid,quantity):
        
        data = {
            "orders":[{
                "conid": conid,
                "orderType": "MKT",
                "side": "SELL",
                "tif": "DAY",
                "quantity": quantity
            }]
        }

        resp = requests.post(url=f"{self.baseUrl}{self.endpoint}", verify=False, json=data)
        respJSON = json.dumps(resp.json())

        # If stale connection
        #   Reauthenticate()
        #   RepeatRequest()

        # If needs order_reply
        #   ibkr.order_reply(returned_id)

        return respJSON
    
    def stop_order(self,conid,quantity,stopPrice):

        data = {
            "orders":[{
                "conid": conid,
                "orderType": "STP",
                "price": stopPrice,
                "side": "BUY",
                "tif": "DAY",
                "quantity": quantity
            }]
        }

        resp = requests.post(url=f"{self.baseUrl}{self.endpoint}", verify=False, json=data)
        respJSON = json.dumps(resp.json())

        # If stale connection
        #   Reauthenticate()
        #   RepeatRequest()

        if resp.status_code >= 300:
            return json.loads('{"message":"Error: Stop Loss Request Failed"}')

        if 'id' in respJSON[0]:
            orderStatus = 'Continue'
        else:
            orderStatus = 'Finished'
        orderJSON = respJSON
        while resp.status_code < 300 and orderStatus != 'Finished':
            orderId = orderJSON[0]['id']
            orderJSON = self.order_reply(orderId)

            # If stale connection
            #   Reauthenticate()
            #   RepeatRequest()

            if 'id' not in orderJSON[0]:
                orderStatus = 'Finished'

        return orderJSON
    
    def order_reply(self,orderId):

        endpoint = f'/iserver/reply/'

        data = {"confirmed":True}

        resp = requests.post(f'{self.baseUrl}{endpoint}{orderId}',verify=False, json=data)
        respJSON = json.dumps(resp.json())

        # If stale connection
        #   Reauthenticate()
        #   RepeatRequest()

        if resp.status_code >= 300:
            return json.loads('[{"message":"Error: Stop Loss Request Failed"}]')

        return respJSON

    def _flatten_contracts_from_companies(self, companiesList):
        """Flatten all contracts from a list of companies."""
        all_contracts = []
        for company in companiesList:
            logger.debug(f"_flatten_contracts_from_companies : company : {company}")
            all_contracts.extend(company['contracts'])
        return all_contracts

    def _flatten_companies_from_symbols(self, symbolsDict):
        """Flatten all companies from a dictionary of symbols."""
        all_companies = []
        for symbol_data in symbolsDict.values():
            all_companies.extend(symbol_data)
        return all_companies

    def _filter_us_exchange_contracts(self, contracts):
        """Filter contracts to only include US exchanges (NASDAQ or NYSE)."""
        filtered_conids = []
        for contract in contracts:
            logger.debug(f"_filter_us_exchange_contracts : contract : {contract}")
            if contract['isUS']:
                if contract['exchange'] == 'NASDAQ' or contract['exchange'] == 'NYSE':
                    filtered_conids.append(contract['conid'])
        return filtered_conids

    def fetch_conid(self,symbol):

        endpoint = f'/trsrv/stocks?symbols={symbol}'

        try:
            resp = requests.get(url=f"{self.baseUrl}{endpoint}", verify=False)
            logger.debug(f'RAW : fetch_conid : {resp.text}')

            respData = resp.json()

            # Flatten all contracts from companies
            all_contracts = self._flatten_contracts_from_companies(respData[symbol])

            # Search through flattened contracts for first matching US exchange
            for contract in all_contracts:
                if contract['isUS']:
                    if contract['exchange'] == 'NASDAQ' or contract['exchange'] == 'NYSE':
                        return contract['conid']

        except Exception as e:
            logger.exception(f"ERROR : fetch_conid('{symbol}') : {e}")
            return None

        return None

    def _list_to_comma_string(self,symbols):
        symbolsString = ''
        for symbol in symbols:
            symbolsString += symbol+','

        return symbolsString

    def fetch_conids(self,symbols):

        # Make sure conids are comma separated list # AAPL,GOOGL,F,AMZN,TSLA
        symbols = self._list_to_comma_string(symbols)
        logger.debug(f"fetch_conids('symbols') : symbols: {symbols}")

        endpoint = f'/trsrv/stocks?symbols={symbols}'

        try:
            resp = requests.get(url=f"{self.baseUrl}{endpoint}", verify=False)
            logger.debug(f'RAW : fetch_conids response : {resp.text}')

            respData = resp.json()

            allCompanies = self._flatten_companies_from_symbols(respData)

            allContracts = self._flatten_contracts_from_companies(allCompanies)

            conids = self._filter_us_exchange_contracts(allContracts)

            return conids

        except Exception as e:
            logger.exception(f"ERROR : fetch_conids({symbols}) : {e}")
            return None

    def fetch_positions(self):

        positionPage = '0'

        endpoint = f'/portfolio/{self.account}/positions/{positionPage}'

        resp = requests.get(f'{self.baseUrl}{endpoint}',verify=False)
        respJSON = json.dumps(resp.json())

        # returns Contracts[]

        return respJSON
    
    def fetch_position(self,symbol):

        conid = self._get_conid_from_symbol(symbol)

        endpoint = f'/portfolio/{self.account}/position/{conid}'

        resp = requests.get(f'{self.baseUrl}{endpoint}',verify=False)
        respJSON = json.dumps(resp.json())

        # returns Contracts[]

        return respJSON
    
    def _summary(self):

        endpoint = f'/portfolio/{self.account}/summary'

        resp = requests.get(f'{self.baseUrl}{endpoint}',verify=False)
        respJSON = json.dumps(resp.json())

        return respJSON

def scratch_conid():

    baseUrl = 'https://localhost:5000/v1/api'
    endpoint = f'/trsrv/stocks?symbols=AAPL'

    resp = requests.get(url=f"{baseUrl}{endpoint}", verify=False)
    # respJSON = json.dumps(resp.json())

    return resp.text

def scratch_limit_order():

    account = os.environ['IBKR_ACCT_NUMBER']
    baseUrl = 'https://localhost:5000/v1/api'
    endpoint = f'/iserver/account/{account}/orders'

    # endpoint = f'/iserver/reply/'

    data = {
        "orders":[{
            "conid": 265598,
            "orderType": "LMT",
            "price": 1,
            "side": "BUY",
            "tif": "DAY",
            "quantity": 1
        }]
    }

    resp = requests.post(url=f"{baseUrl}{endpoint}", verify=False, json=data)
    respJSON = json.dumps(resp.json())

    return respJSON
# print(scratch_conid())
ibkr = IBKRClient()
# print(ibkr.fetch_conid('AAPL'))
# print(ibkr.fetch_conids(['AAPL','GOOGL','F','TSLA']))
symbol = ['AAPL','GOOGL']
print(ibkr.fetch_conids(symbol))