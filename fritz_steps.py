import time
import requests
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from browser_utils import klicken, schreiben, sicher_warten

FRITZ_URL = "http://fritz.box"
tim_version_cache = {"version": None}

def beende_browser(driver):
    if driver:
        driver.quit()

def warte_auf_fritzbox(versuche=20, delay=5):
    global FRITZ_URL
    ip_list = [
        "http://fritz.box",
        "http://192.168.178.1",
        "http://169.254.139.1",
        "http://169.254.1.1",
    ]

    print("🔍 Suche erreichbare FritzBox...")

    for _ in range(versuche):
        for url in ip_list:
            try:
                r = requests.get(url, timeout=3, verify=False, allow_redirects=False)
                if r.status_code == 200:
                    FRITZ_URL = url
                    print(f"✅ FritzBox erreichbar unter {url}")
                    return True
            except:
                pass
        time.sleep(delay)

    print("❌ FritzBox nicht erreichbar.")
    return False

def check_login_state(driver):
    try:
        # Prüfe, ob typischer Login-Screen geladen ist (z. B. Passwortfeld)
        if driver.find_elements(By.XPATH, '//input[@type="password"]'):
            print("🔐 Nutzer ausgeloggt – Login wird erneut durchgeführt...")
            login(driver)
            return True
        return False
    except Exception:
        return False


def ist_sprachauswahl(driver):
    if not warte_auf_fritzbox():
        raise Exception("FritzBox nicht erreichbar.")
    try:
        driver.get(FRITZ_URL)
        sicher_warten(driver, '//*[@id="uiLanguage-de"]', timeout=5)
        return True
    except Exception as e:
        pass
    try:
        driver.get(FRITZ_URL)
        sicher_warten(driver, '//*[@id="uiLanguage-en"]', timeout=5)
        return True
    except Exception as e:
        return False

def login(driver, password=None, need_reload=False):
    if not warte_auf_fritzbox():
        raise Exception("FritzBox nicht erreichbar für Login.")
    print("🔐 Login...")

    for attempt in range(3):
        if not password:
            password = input("🔑 Passwort: ").strip()

        driver.get(FRITZ_URL)

        # Check for login field
        try:
            WebDriverWait(driver, 3).until(EC.presence_of_element_located((By.XPATH, '//*[@id="uiPass"]')))
        except:
            # Check for sprachauswahl
            if ist_sprachauswahl(driver):
                try:
                    klicken(driver, '//*[@id="uiLanguage-en"]')  # Defaulting to DE
                    klicken(driver, '//*[@id="submitLangBtn"]')
                    time.sleep(5)
                except:
                    print("⚠️ Sprachauswahl fehlgeschlagen.")
                if need_reload:
                    driver.get(FRITZ_URL)
            else:
                print("❌ Login-Feld nicht gefunden.")
                continue

        try:
            schreiben(driver, '//*[@id="uiPass"]', password)
            klicken(driver, '//*[@id="submitLoginBtn"]')

            WebDriverWait(driver, 5).until(EC.presence_of_element_located((By.ID, "content")))
            print("✅ Login erfolgreich.")

            # Post-login dialogs
            post_login_cleanup(driver)
            return

        except Exception as e:
            print("❌ Login fehlgeschlagen.")
            password = None
            if attempt == 2:
                raise Exception("🚫 Login 3x fehlgeschlagen.")

def post_login_cleanup(driver): # when skip configuration was successfull
    # neuer Firmware-Dialog muss noch behandelt werden (Button 1 3x)
    dsl_setup_init(driver) # diese schritte sollten abbrechen, wenn das element nicht vorhanden ist...
    checkbox_fehlerdaten_dialog(driver)
    if not skip_configuration(driver):
        dsl_setup_wizard(driver)



def reset_fritzbox(driver): #without login
    if not warte_auf_fritzbox():
        raise Exception("FritzBox nicht erreichbar für Reset.")
    print("🚨 Werkseinstellungen einleiten...")
    driver.get(FRITZ_URL)

    kandidaten = [
        '//*[@id="dialogFoot"]/a',
        '//a[contains(text(), "Passwort vergessen")]',
        '//button[contains(text(), "Passwort vergessen")]',
        '//a[contains(text(), "Kennwort vergessen")]',
        '//button[contains(text(), "Kennwort vergessen")]',
    ]

    for xpath in kandidaten:
        try:
            klicken(driver, xpath)
            print(f"🔁 Reset-Link gefunden ({xpath})")
            break
        except:
            continue
    else:
        print("❌ Kein Reset-Link gefunden.")
        return False

    try:
        klicken(driver, '//*[@id="sendFacReset"]')
        print("🔁 Reset ausgelöst, warte auf Neustart...")
        time.sleep(50)
        return True

    except Exception:
        print("❌ Fehler beim Bestätigen des Resets.")
        return False

def checkbox_fehlerdaten_dialog(driver):
    print("🛑 Fehlerdaten-Checkbox prüfen...")
    try:
        checkbox = sicher_warten(driver, '//*[@id="uiTr069diag"]', timeout=5)
        if checkbox.is_selected():
            checkbox.click()
            print("☑️ Deaktiviert.")
        else:
            print("☑️ Bereits deaktiviert.")
    except:
        print("ℹ️ Keine Checkbox gefunden.")
        return

    try:
        klicken(driver, '//*[@id="uiApply"]')
        print("➡️ Übernommen.")
    except:
        pass

def wlan_antenne_check(driver, max_versuche=2):
    print("📡 WLAN-Antennen prüfen...")

    for versuch in range(1, max_versuche + 1):
        try:
            klicken(driver, '//*[@id="wlan"]')
            klicken(driver, '//*[@id="chan"]')
            WebDriverWait(driver, 20).until(
                EC.presence_of_element_located(
                (By.XPATH, '//div[@class="flexRow" and .//div[@prefid="rssi"]]'))
            )
            rows = driver.find_elements(By.XPATH, '//div[@class="flexRow" and .//div[@prefid="rssi"]]')
            if rows:
                print(f"📶 {len(rows)} Netzwerke gefunden. Verarbeite...")
                break
            else:
                print(f"⚠️ Kein WLAN gefunden (Versuch {versuch}/{max_versuche}).")
        except Exception as e:
            print(f"❌ Fehler beim Zugriff auf WLAN-Liste (Versuch {versuch})")
            rows = []

        if versuch < max_versuche:
            print("🔁 Neuer Versuch in 5 Sekunden...")
            time.sleep(5)
        else:
            raise Exception("❌ Auch nach mehreren Versuchen keine Netzwerke gefunden.")

    print("\n📋 Ergebnisübersicht:\n")
    for i in range(len(rows)):
        try:
            # Frisch halten: jedes Row-Element im Loop neu holen
            row_xpath = f'(//div[@class="flexRow" and .//div[@prefid="rssi"]])[{i + 1}]'
            row = driver.find_element(By.XPATH, row_xpath)

            name = row.find_element(By.XPATH, './/div[@prefid="name"]').text.strip()
            freq = row.find_element(By.XPATH, './/div[@prefid="band"]').text.strip()
            channel = row.find_element(By.XPATH, './/div[@prefid="channel"]').text.strip()
            mac = row.find_element(By.XPATH, './/div[@prefid="mac"]').text.strip()
            signal_title = row.find_element(By.XPATH, './/div[@prefid="rssi"]').get_attribute("title").strip()

            signal_val = signal_title.replace('%', '')
            signal_strength = 20 if signal_val.startswith('<') else int(signal_val or 0)

            if signal_strength <= 30:
                emoji = "📶🔴"
            elif signal_strength <= 60:
                emoji = "📶🟡"
            else:
                emoji = "📶🟢"

            print(f"{i+1}. {name} | {freq} | Kanal {channel} | MAC: {mac} | Signal: {signal_title} {emoji}")

        except Exception as e:
            print(f"⚠️ Fehler beim Verarbeiten eines Netzwerks (#{i+1}).")

def firmware_update(driver, path):
    print("🆙 Firmware-Update...")
    klicken(driver, '//*[@id="sys"]')
    klicken(driver, '//*[@id="mUp"]')
    klicken(driver, '//*[@id="userUp"]')

    try:
        checkbox = sicher_warten(driver, '//*[@id="uiExportCheck"]', timeout=10)
        if checkbox.is_selected():
            checkbox.click()
    except:
        pass

    schreiben(driver, '//*[@id="uiFile"]', path)
    klicken(driver, '//*[@id="uiUpdate"]')
    print("📤 Firmware wird hochgeladen...")

    try:
        sicher_warten(driver, '//*[@id="submitLoginBtn"]', timeout=300)
        print("✅ Update abgeschlossen.")
    except:
        print("⚠️ Kein Redirect erkannt – versuche manuell.")
        if warte_auf_fritzbox():
            driver.get(FRITZ_URL)

def firmware_version_pruefen(driver):
    klicken(driver,'//*[@id="wlan"]')
    klicken(driver,'//*[@id="sys"]')
    klicken(driver,'//*[@id="mUp"]')
    version_elem = sicher_warten(driver, '//*[@class="fakeTextInput"]')
    version_text = version_elem.text.strip()

    if version_text:
        print(f"ℹ️ Firmware-Version: {version_text}")
        return version_text
    else:
        print("❌ Keine Version gefunden.")
        return None

def firmware_version_pruefen_wrapper(driver):
    version = firmware_version_pruefen(driver)
    tim_version_cache["version"] = version

def erstelle_standard_steps(password, firmware_pfad):
    return [
        ("Login durchführen", lambda d: login(d, password)),
        ("Firmware-Version prüfen", firmware_version_pruefen_wrapper),
        ("Firmware-Update oder Reset durchführen", lambda d: tim_update_oder_reset(d, firmware_pfad)),
        ("WLAN-Antennen prüfen", wlan_antenne_check),
    ]

def get_steps_from_branding(driver, password, firmware_pfad):
    print("🔍 Prüfe Branding / Modell...")

    try:
        driver.get(FRITZ_URL)
        time.sleep(2)

        branding_text = ""
        try:
            branding_elem = driver.find_element(By.XPATH, '//*[contains(text(), "Telekom") or contains(text(), "TIM")]')
            branding_text = branding_elem.text.lower()
        except:
            pass

        if "tim" in branding_text:
            print("🇮🇹 TIM-Branding erkannt.")
        else:
            print("🇩🇪 Standard-FritzBox erkannt.")

        # Unify steps regardless of branding
        return erstelle_standard_steps(password, firmware_pfad)

    except Exception as e:
        print(f"⚠️ Branding-Erkennung fehlgeschlagen")
        return erstelle_standard_steps(password, firmware_pfad)

def dsl_setup_init(driver):
    print("⚙️ Setze default DSL-Settings...")
    try:
        sicher_warten(driver, '//*[@id="uiForward"]')
    except Exception as e:
        print("DSL-Setup nicht aufrufbar")
        return
    for xpath in [
        '//*[@id="uiForward"]',
        '//*[@id="uiForward"]'
    ]:
        try:
            klicken(driver, xpath)
            time.sleep(2)
        except Exception as e:
            print(f"⚠️ Scheinbar kein DSL-Init notwendig.")
            return

def neue_firmware_dialog(driver):
    print("Prüfe ob neue Firmware-installiert wurde.")
    try:
        sicher_warten(driver,'//a[contains(text(), "OK")]',)
    except Exception as e:
        print("Keine neue FW installiert.")
        return
    for xpath in [
        '//a[contains(text(), "Weiter")]',
        '//a[contains(text(), "OK")]'
    ]:
        try:
            klicken(driver, xpath)
            time.sleep(2)
        except Exception as e:
            print(f"⚠️ Scheinbar kein DSL-Init notwendig.")
            return




def dsl_setup_wizard(driver):
    print("⚙️ Setup-Wizard komplett durchlaufen (DSL)...")
    try:
        klicken(driver, '//*[@id="dlg_welcome"]/p[3]/a')
    except:
        print("⚠️ Kein Direktlink – manueller Ablauf.")
        for xpath in [
            '//*[@id="uiForward"]', '//*[@id="uiSkip"]', '//*[@id="uiSkip"]',
            '//*[@id="uiWizFooterBtns"]/button', '//*[@id="uiWizFooterBtns"]/button',
            '//*[@id="uiWizFooterBtns"]/button', '//*[@id="uiFinish"]',
            '//*[@id="Button1"]'
        ]:
            try:
                klicken(driver, xpath)
                time.sleep(2)
            except Exception as e:
                print(f"⚠️ Wizard-Fehler: {xpath}\n DSL Wizzard geschlossen.")

def tim_factory_reset(driver):
    print("🚨 Werkseinstellungen (aus der Oberfläche)...")

    try:
        # Nur auf "System" klicken, wenn "mSave" NICHT da ist
        try:
            sicher_warten(driver, '//*[@id="mSave"]', timeout=5)
            print("✅ Menü bereits offen – kein Klick auf 'System' nötig.")
        except:
            print("📂 Öffne 'System'-Menü...")
            klicken(driver, '//*[@id="sys"]')
            time.sleep(1)

        # Danach reguläre Klicks nacheinander
        for xpath in [
            '//*[@id="mSave"]',
            '//*[@id="default"]',
            '//*[@id="content"]/div/button',
            '//*[@id="Button1"]'
        ]:
            try:
                klicken(driver, xpath)
                time.sleep(3)
            except Exception as e:
                print(f"⚠️ Fehler bei Reset-Klick: {xpath}")
    except Exception as e:
        print(f"❌ Fehler im Reset-Ablauf:")
        return

    print("⚠️ℹ️⚠️ Bitte jetzt physischen Knopf an der Box drücken...")

    # Warte auf OK-Button
    try:
        def finde_und_klicke_ok(driver):
            for btn in driver.find_elements(By.ID, "Button1"):
                if "OK" in btn.text:
                    btn.click()
                    return True

            return False

        WebDriverWait(driver, 180).until(finde_und_klicke_ok)
        print("✅ OK-Button geklickt.")
    except Exception as e:
        print(f"❌ Fehler bei OK-Klick: {e}")
        raise("Fehler beim bestätigen des Werkseinstellungsreset.")

    time.sleep(25)
    if ist_sprachauswahl(driver):
        print("✅ Erfolgreich auf Werkseinstellungen zurückgesetzt.")
    else:
        print("⚠️ Nicht verifiziert – bitte manuell prüfen.")


def tim_update_oder_reset(driver, firmware_pfad):
    version = tim_version_cache.get("version", "")
    if version == "8.03":
        print("🔁 Version 8.03 erkannt – Reset statt Update.")
        tim_factory_reset(driver)
        return
    firmware_update(driver, firmware_pfad)


def skip_configuration(driver):
    print("📌 Konfigurationsdialog überspringen...")
    try:
        for _ in range(2):

            placeholder_elem = WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.XPATH, '//*[@id="Button1"]'))
            )
            if placeholder_elem:
                placeholder_elem.click()
                print("✅ Platzhalter-Button gedrückt.")
                time.sleep(2)
    except:
        print("ℹ️ Kein Konfigurationsdialog erkannt oder Timeout.")
        return False
    return True

