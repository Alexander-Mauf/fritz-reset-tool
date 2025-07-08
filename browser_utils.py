from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium import webdriver
import time


def setup_browser():
    options = Options()
    # options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_argument("--ignore-certificate-errors")
    options.add_argument("--log-level=3")
    options.add_argument("--window-size=1920,1080")
    return webdriver.Chrome(service=Service("chromedriver.exe"), options=options)


def sicher_warten(driver, locator, timeout=10, sichtbar=True, mehrere=False):
    if isinstance(locator, str):
        locator = (By.XPATH, locator)
    wait = WebDriverWait(driver, timeout)
    from fritz_steps import check_login_state

    for versuch in range(2):  # max 2 Versuche: normal + nach Re-Login
        try:
            if mehrere:
                if sichtbar:
                    return wait.until(EC.visibility_of_all_elements_located(locator))
                else:
                    return wait.until(EC.presence_of_all_elements_located(locator))
            else:
                if sichtbar:
                    return wait.until(EC.visibility_of_element_located(locator))
                else:
                    return wait.until(EC.presence_of_element_located(locator))
        except Exception as e:
            if check_login_state(driver):
                print("🔁 Wiederhole warten nach Re-Login...")
                continue
            raise Exception(f"❌ Fehler beim Warten auf Element: {locator}")
    raise Exception(f"❌ Fehler beim Warten auf Element: {locator}")

def klicken(driver, xpath, timeout=15, versuche=3):
    for i in range(versuche):
        try:
            element = sicher_warten(driver, xpath, timeout)
            try:
                element.click()
                return True
            except Exception as e:
                print(f"⚠️ Klick direkt nicht möglich (Versuch {i + 1}): {e}")
                driver.execute_script("arguments[0].click();", element)
                return True
        except Exception as e:
            time.sleep(1)
    print(f"❌ Element nicht klickbar nach {versuche} Versuchen: {xpath}")
    return False


def schreiben(driver, xpath, text, timeout=30):
    sicher_warten(driver, xpath, timeout).send_keys(text)
