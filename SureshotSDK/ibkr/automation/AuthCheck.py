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
    print(response)
    print(response.text)

    # if response.status_code == 401:
    #   reAuthenticate() -> Playwright; Click on https://localhost:5000/; login with credentials, make sure credentials are in ENV or Vault
    # Snag Security Code from 2FA; 1password?
    #   ...
    
if __name__ == "__main__":
    try:
        confirm_auth()
    except requests.exceptions.ConnectionError as e:
        logging.error('RUN BASH!!!')
        logging.error(e)