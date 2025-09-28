import requests
import os

class PolygonMiddleware:
    def __init__(self, apiKey=None):
        if not apiKey:
            apiKey = os.getenv("POLYGON_API_KEY")
        if not apiKey:
            raise ValueError("API key must be provided either as an argument or via the POLYGON_API_KEY environment variable.")

        self.apiKey = apiKey
        self.baseUrl = 'https://api.polygon.io/'

    def fetch_close(self, symbol, multiplier, timespan, startDate, endDate):
        url = f'{self.baseUrl}/v2/aggs/ticker/{symbol}/range/{multiplier}/{timespan}/{startDate}/{endDate}?sort=desc&limit=1'

        headers = {
            'Authorization': f'Bearer {self.apiKey}',
            'Accept': 'application/json'
        }
        response = requests.get(url, headers=headers)
        responseBody = response.json()
        return responseBody['results'][0]['c']

    def fetch_candle(self, symbol, multiplier, timespan, startDate, endDate):
        url = f'{self.baseUrl}/v2/aggs/ticker/{symbol}/range/{multiplier}/{timespan}/{startDate}/{endDate}?sort=desc&limit=1'

        headers = {
            'Authorization': f'Bearer {self.apiKey}',
            'Accept': 'application/json'
        }
        response = requests.get(url, headers=headers)
        responseBody = response.json()
        return responseBody['results'][0]

    def fetch_candles(self, symbol, multiplier, timespan, startDate, endDate):
        url = f'{self.baseUrl}/v2/aggs/ticker/{symbol}/range/{multiplier}/{timespan}/{startDate}/{endDate}'

        headers = {
            'Authorization': f'Bearer {self.apiKey}',
            'Accept': 'application/json'
        }
        response = requests.get(url, headers=headers)
        responseBody = response.json()
        # TODO: handle pagination
        #   if responseBody.next_url:
        #   we need all the candles, but we need to call them efficiently
        return responseBody