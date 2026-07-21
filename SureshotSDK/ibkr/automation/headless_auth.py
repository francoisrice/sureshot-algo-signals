import asyncio
from playwright.sync_api import sync_playwright
from playwright.async_api import async_playwright
import pyotp
import os
import logging
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)

GATEWAY_URL = os.environ.get('IBKR_GATEWAY_HTTP_URL', 'https://localhost:5000')


def _log_failure_context(page, prefix):
    try:
        page.screenshot(path=f'{prefix}.png')
    except Exception as e:
        logger.warning(f"Could not capture screenshot: {e}")
    try:
        logger.error(
            f"Login flow failed at url={page.url!r} title={page.title()!r} "
            f"content={page.content()[:2000]!r}"
        )
    except Exception as e:
        logger.warning(f"Could not capture page content: {e}")


async def _log_failure_context_async(page, prefix):
    try:
        await page.screenshot(path=f'{prefix}.png')
    except Exception as e:
        logger.warning(f"Could not capture screenshot: {e}")
    try:
        logger.error(
            f"Login flow failed at url={page.url!r} title={await page.title()!r} "
            f"content={(await page.content())[:2000]!r}"
        )
    except Exception as e:
        logger.warning(f"Could not capture page content: {e}")


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
        try:
            context = browser.new_context(ignore_https_errors=True)
            page = context.new_page()
            try:
                page.goto(f'{GATEWAY_URL}/')
                page.wait_for_selector('#xyz-field-username', state='visible', timeout=45000)
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
                    return "Login Successful"
                except Exception:
                    _log_failure_context(page, 'Failed_Login')
                    return "Login Failed"
            except Exception:
                _log_failure_context(page, 'Failed_Login')
                raise
        finally:
            browser.close()


async def async_login():
    loginA, loginB, loginC = _get_credentials()
    async with async_playwright() as session:
        browser = await session.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-dev-shm-usage']
        )
        try:
            context = await browser.new_context(ignore_https_errors=True)
            page = await context.new_page()
            try:
                await page.goto(f'{GATEWAY_URL}/')
                await page.wait_for_selector('#xyz-field-username', state='visible', timeout=45000)
                await page.fill('#xyz-field-username', loginA)
                await page.fill('#xyz-field-password', loginB)
                await page.click('button[type="submit"]')
                await page.wait_for_selector('.xyz-multipleselect', state='visible')
                await page.select_option('.xyz-multipleselect', value='4')
                await page.wait_for_selector('#xyz-field-silver-response', state='visible')
                await page.fill('#xyz-field-silver-response', get_totp_code(loginC))
                await page.locator('button:has-text("Login")').locator('visible=true').first.click()
                try:
                    await page.wait_for_selector('text=Client login succeeds', timeout=5000)
                    return "Login Successful"
                except Exception:
                    await _log_failure_context_async(page, 'Failed_Login')
                    return "Login Failed"
            except Exception:
                await _log_failure_context_async(page, 'Failed_Login')
                raise
        finally:
            await browser.close()


if __name__ == "__main__":
    print(sync_login())
