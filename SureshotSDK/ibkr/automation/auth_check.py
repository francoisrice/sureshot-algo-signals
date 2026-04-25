import requests
import logging
import os
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logging.basicConfig(level=logging.INFO)

GATEWAY_BASE_URL = os.environ.get('IBKR_GATEWAY_URL', 'https://localhost:5000/v1/api')


def confirm_auth():
    response = requests.get(url=f"{GATEWAY_BASE_URL}/iserver/auth/status", verify=False)
    logging.debug(response.text)
    return response


if __name__ == "__main__":
    try:
        logging.info(confirm_auth())
    except requests.exceptions.ConnectionError as e:
        logging.error('Gateway unreachable — is the Client Portal Gateway running?')
        logging.error(e)
