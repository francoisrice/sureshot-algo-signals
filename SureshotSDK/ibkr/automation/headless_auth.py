import asyncio
from playwright.sync_api import sync_playwright
from playwright.async_api import async_playwright
import pyotp
import os

def _get_credentials():
    loginA = os.environ.get('IBKR_USERNAME')
    loginB = os.environ.get('IBKR_PASSWORD')
    loginC = os.environ.get('IBKR_SECRET')

    errorMsg = 'Missing Auth Credentials:'
    if not loginA:
        errorMsg += ' username '
    if not loginB:
        errorMsg += ' password '
    if not loginC:
        errorMsg += ' otp secret '
    if errorMsg != 'Missing Auth Credentials:':
        raise(Exception(errorMsg))

    return loginA, loginB, loginC

headless=False
method='sync'

import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def get_totp_code(secret):
      totp = pyotp.TOTP(secret)
      return totp.now()

def sync_login():
    loginA, loginB, loginC = _get_credentials()
    with sync_playwright() as session:
        browser = session.chromium.launch(headless=headless)
        context = browser.new_context(ignore_https_errors=True)
        page = context.new_page()
        page.goto('https://localhost:5000/')
        page.wait_for_load_state('networkidle')
        page.fill('#xyz-field-username',loginA)
        page.fill('#xyz-field-password',loginB)

        # Wait for 2FA field to appear after clicking submit
        page.click('button[type="submit"]')

        # Select MFA method - Mobile Authenticator App (value="4")
        page.wait_for_selector('.xyz-multipleselect', state='visible')
        page.select_option('.xyz-multipleselect', value='4')

        # Fill MFA input field
        page.wait_for_selector('#xyz-field-silver-response', state='visible')
        page.fill('#xyz-field-silver-response',get_totp_code(loginC))

        # Click the visible Login button
        page.locator('button:has-text("Login")').locator('visible=true').first.click()

        try:
            # Wait for the text to appear (with timeout)
            page.wait_for_selector('text=Client login succeeds', timeout=5000)
            print("Login Successful")
            browser.close()
            return "Login Successful"
        except:
            print("Login Failed")
            page.screenshot(path='Failed_Login.png')

async def main():
    async with async_playwright() as session:
        browser = await session.chromium.launch(headless=headless)
        page = await browser.new_page()
        await page.goto('https://localhost:5000')
        await page.screenshot(path='example.png')
        await browser.close()

if __name__ == "__main__":
    if method == 'sync':
        sync_login()
    else:
        asyncio.run(main())
