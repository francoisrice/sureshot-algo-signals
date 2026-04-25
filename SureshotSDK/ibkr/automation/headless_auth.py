import asyncio
from playwright.sync_api import sync_playwright
from playwright.async_api import async_playwright
import pyotp
import os
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

GATEWAY_URL = os.environ.get('IBKR_GATEWAY_HTTP_URL', 'https://localhost:5000')


def _get_credentials():
    loginA = os.environ.get('IBKR_USERNAME')
    loginB = os.environ.get('IBKR_PASSWORD')
    loginC = os.environ.get('IBKR_SECRET')

    missing = []
    if not loginA: missing.append('IBKR_USERNAME')
    if not loginB: missing.append('IBKR_PASSWORD')
    if not loginC: missing.append('IBKR_SECRET')
    if missing:
        raise Exception(f'Missing auth credentials: {", ".join(missing)}')

    return loginA, loginB, loginC


def get_totp_code(secret):
    totp = pyotp.TOTP(secret)
    return totp.now()


def sync_login():
    loginA, loginB, loginC = _get_credentials()
    with sync_playwright() as session:
        browser = session.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-dev-shm-usage']
        )
        context = browser.new_context(ignore_https_errors=True)
        page = context.new_page()
        page.goto(f'{GATEWAY_URL}/')
        page.wait_for_load_state('networkidle')
        page.fill('#xyz-field-username', loginA)
        page.fill('#xyz-field-password', loginB)

        page.click('button[type="submit"]')

        page.wait_for_selector('.xyz-multipleselect', state='visible')
        page.select_option('.xyz-multipleselect', value='4')

        page.wait_for_selector('#xyz-field-silver-response', state='visible')
        page.fill('#xyz-field-silver-response', get_totp_code(loginC))

        page.locator('button:has-text("Login")').locator('visible=true').first.click()

        try:
            page.wait_for_selector('text=Client login succeeds', timeout=5000)
            browser.close()
            return "Login Successful"
        except Exception:
            page.screenshot(path='Failed_Login.png')
            browser.close()
            return "Login Failed"


if __name__ == "__main__":
    print(sync_login())
