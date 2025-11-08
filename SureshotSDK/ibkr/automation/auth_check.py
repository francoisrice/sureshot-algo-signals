import requests
import logging

# Suppress the warnings for insecure certificates
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logging.basicConfig(level=logging.INFO)

def confirm_auth():
    baseUrl = 'https://localhost:5000/v1/api'
    endpoint = '/iserver/auth/status'

    response = requests.get(url=f"{baseUrl}{endpoint}", verify=False)
    logging.debug(response)
    logging.debug(response.text)

    return response
    
if __name__ == "__main__":
    try:
        logging.info(confirm_auth())
    except requests.exceptions.ConnectionError as e:
        logging.error('RUN BASH!!!')
        logging.error(e)