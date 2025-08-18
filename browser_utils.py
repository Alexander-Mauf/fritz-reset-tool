# browser_utils.py
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium import webdriver
import time

def setup_browser():
    """Initialisiert und konfiguriert den Chrome WebDriver."""
    options = Options()
    # options.add_argument("--headless=new") # Optional: Für Headless-Betrieb
    options.add_argument("--disable-gpu")
    options.add_argument("--ignore-certificate-errors")
    options.add_argument("--log-level=3") # Weniger WebDriver-Logs
    options.add_argument("--window-size=1920,1080")
    # Stelle sicher, dass chromedriver.exe im PATH oder im gleichen Verzeichnis ist
    return webdriver.Chrome(service=Service("chromedriver.exe"), options=options)

class Browser:
    """Kapselt Browser-spezifische Operationen mit Selenium WebDriver."""

    def __init__(self, driver: webdriver.Chrome):
        if not isinstance(driver, webdriver.Chrome):
            raise TypeError("Der übergebene Treiber muss eine Instanz von selenium.webdriver.Chrome sein.")
        self.driver = driver

    def sicher_warten(self, locator, timeout=10, sichtbar=True, mehrere=False):
        """
        Wartet sicher auf ein Element oder Elemente.
        Locator kann ein (By.XPATH, "xpath_string") Tupel oder ein reiner XPath-String sein.
        """
        if isinstance(locator, str):
            locator = (By.XPATH, locator) # Standardmäßig XPath verwenden

        wait = WebDriverWait(self.driver, timeout)
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
            # Hier keine Fritzbox-spezifische Login-Prüfung, da dies eine generische Browser-Klasse ist.
            # Die Login-Prüfung erfolgt in der FritzBox-Klasse, die diese Browser-Methoden nutzt.
            raise Exception(f"❌ Fehler beim Warten auf Element {locator} (Timeout/Nicht gefunden)")

    def klicken(self, xpath, timeout=15, versuche=3, verbose=False):
        """
        Klickt auf ein Element, versucht bei Fehlschlag JavaScript-Klick.
        Gibt True bei Erfolg, False bei Fehlschlag zurück.
        """
        for i in range(versuche):
            try:
                element = self.sicher_warten(xpath, timeout)
                try:
                    element.click()
                    return True
                except Exception as e:
                    # Direkter Klick fehlgeschlagen, versuche JavaScript-Klick
                    print(f"⚠️ Klick direkt nicht möglich (Versuch {i + 1}) für {xpath}")
                    self.driver.execute_script("arguments[0].click();", element)
                    return True # JavaScript-Klick war (wahrscheinlich) erfolgreich
            except Exception as e:
                if verbose:
                    print(f"⚠️ Element {xpath} beim Warten nicht gefunden (Versuch {i + 1})")
                    time.sleep(1) # Kurze Pause vor dem nächsten Versuch
                else:
                    print(f"⚠️ Element {xpath} beim Warten nicht gefunden (Versuch {i + 1})")
                    time.sleep(1)  # Kurze Pause vor dem nächsten Versuch
        print(f"❌ Element {xpath} nicht klickbar nach {versuche} Versuchen.")
        return False

    def schreiben(self, xpath, text, timeout=30):
        """Schreibt Text in ein Feld."""
        try:
            element = self.sicher_warten(xpath, timeout)
            element.send_keys(text)
            return True
        except Exception as e:
            print(f"❌ Fehler beim Schreiben in {xpath}")
            return False

    def get_url(self, url):
        """Navigiert zu einer URL."""
        try:
            self.driver.get(url)
            return True
        except Exception as e:
            print(f"❌ Fehler beim Navigieren zu {url}")
            return False

    def reload(self, url, cache_bust=True, clear_cookies=True):
        """Erneutes Laden der Seite inkl. einfacher Cache-Umgehung."""
        try:
            if self.driver is None:
                print("❌ Browser-Driver ist None (geschlossen).")
                return False
            if clear_cookies:
                try:
                    self.driver.delete_all_cookies()
                except Exception:
                    pass
            final = url
            if cache_bust:
                ts = int(time.time() * 1000)
                sep = '&' if ('?' in url) else '?'
                final = f"{url}{sep}_={ts}"
            self.driver.get(final)
            return True
        except Exception:
            print("❌ Fehler bei reload()")
            return False


    def quit(self):
        """Schließt den Browser."""
        if self.driver:
            print("🌐 Browser wird geschlossen.")
            self.driver.quit()
            self.driver = None # Setze den Driver auf None, um weitere Operationen zu verhindern
            return True
        return False