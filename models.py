import os
from pathlib import Path
import time
import requests
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import tkinter as tk
from tkinter import filedialog # Für den Fallback-Dateiauswahldialog

# Eine Konstante für die Standard-Fritzbox-URL
FRITZ_DEFAULT_URL = "http://fritz.box"

class Browser:
    """Kapselt Browser-spezifische Operationen."""

    def __init__(self, driver: webdriver.Chrome):
        self.driver = driver

    def sicher_warten(self, locator, timeout=10, sichtbar=True, mehrere=False):
        """Wartet sicher auf ein Element oder Elemente."""
        if isinstance(locator, str):
            locator = (By.XPATH, locator)
        wait = WebDriverWait(self.driver, timeout)

        # Die Re-Login-Logik muss von einer übergeordneten Klasse (FritzBox) behandelt werden.
        # Hier geht es nur um das Warten.
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
            raise Exception(f"❌ Fehler beim Warten auf Element {locator}: {e}")

    def klicken(self, xpath, timeout=15, versuche=3):
        """Klickt auf ein Element, versucht bei Fehlschlag JavaScript-Klick."""
        for i in range(versuche):
            try:
                element = self.sicher_warten(xpath, timeout)
                try:
                    element.click()
                    return True
                except Exception as e:
                    print(f"⚠️ Klick direkt nicht möglich (Versuch {i + 1}): {e}")
                    self.driver.execute_script("arguments[0].click();", element)
                    return True
            except Exception as e:
                time.sleep(1)
        print(f"❌ Element nicht klickbar nach {versuche} Versuchen: {xpath}")
        return False

    def schreiben(self, xpath, text, timeout=30):
        """Schreibt Text in ein Feld."""
        self.sicher_warten(xpath, timeout).send_keys(text)

    def get_url(self, url):
        """Navigiert zu einer URL."""
        self.driver.get(url)

    def quit(self):
        """Schließt den Browser."""
        if self.driver:
            self.driver.quit()

class FritzBox:
    """Repräsentiert eine FritzBox und kapselt ihre Interaktionen."""

    def __init__(self, driver: webdriver.Chrome):
        self.browser = Browser(driver)
        self.url = FRITZ_DEFAULT_URL
        self.os_version = None
        self.is_reset = False
        self.language = None
        self.is_logged_in = False
        self.password = None
        self.box_model = None # Neu: Um das Modell zu speichern
        self.is_wifi_checked = False

    def warte_auf_erreichbarkeit(self, versuche=20, delay=5):
        """Wartet, bis die FritzBox unter einer bekannten IP erreichbar ist."""
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
                        self.url = url
                        print(f"✅ FritzBox erreichbar unter {url}")
                        return True
                except requests.exceptions.ConnectionError:
                    pass # Verbindung fehlgeschlagen, probiere nächste URL oder warte
                except Exception as e:
                    print(f"Fehler beim Prüfen der URL {url}: {e}")
            time.sleep(delay)

        print("❌ FritzBox nicht erreichbar.")
        return False

    def check_login_state(self):
        """Prüft, ob ein Login nötig ist und führt ihn ggf. durch."""
        try:
            # Prüfe, ob typischer Login-Screen geladen ist (z.B. Passwortfeld)
            if self.browser.driver.find_elements(By.XPATH, '//input[@type="password"]'):
                print("🔐 Nutzer ausgeloggt – Login wird erneut durchgeführt...")
                self.login(self.password, need_reload=True) # Nutze das gespeicherte Passwort
                return True
            return False
        except Exception:
            return False

    def ist_sprachauswahl(self):
        """Prüft, ob die Sprachauswahl-Seite angezeigt wird."""
        if not self.warte_auf_erreichbarkeit():
            raise Exception("FritzBox nicht erreichbar.")
        try:
            self.browser.get_url(self.url)
            self.browser.sicher_warten('//*[@id="uiLanguage-de"]', timeout=5)
            return True
        except Exception:
            pass
        try:
            self.browser.get_url(self.url)
            self.browser.sicher_warten('//*[@id="uiLanguage-en"]', timeout=5)
            return True
        except Exception:
            return False

    def login(self, password=None, need_reload=False):
        """Führt den Login in die FritzBox durch."""
        if not self.warte_auf_erreichbarkeit():
            raise Exception("FritzBox nicht erreichbar für Login.")
        print("🔐 Login...")

        for attempt in range(3):
            if not password:
                password = input("🔑 Passwort: ").strip()
            self.password = password # Speichere das Passwort für spätere Re-Logins

            self.browser.get_url(self.url)

            try:
                WebDriverWait(self.browser.driver, 3).until(EC.presence_of_element_located((By.XPATH, '//*[@id="uiPass"]')))
            except:
                if self.ist_sprachauswahl():
                    try:
                        # Setze Sprache auf Englisch (oder Deutsch, je nach Präferenz)
                        self.browser.klicken('//*[@id="uiLanguage-en"]') # oder 'uiLanguage-de'
                        self.browser.klicken('//*[@id="submitLangBtn"]')
                        time.sleep(5)
                    except:
                        print("⚠️ Sprachauswahl fehlgeschlagen.")
                    if need_reload:
                        self.browser.get_url(self.url)
                else:
                    print("❌ Login-Feld nicht gefunden.")
                    continue

            try:
                self.browser.schreiben('//*[@id="uiPass"]', password)
                self.browser.klicken('//*[@id="submitLoginBtn"]')

                WebDriverWait(self.browser.driver, 5).until(EC.presence_of_element_located((By.ID, "content")))
                print("✅ Login erfolgreich.")
                self.is_logged_in = True

                self.post_login_cleanup()
                return

            except Exception as e:
                print(f"❌ Login fehlgeschlagen: {e}")
                password = None
                if attempt == 2:
                    raise Exception("🚫 Login 3x fehlgeschlagen.")

    def post_login_cleanup(self):
        """Führt nach dem Login notwendige Aufräumaktionen durch (Dialoge etc.)."""
        # Diese Methoden müssen noch als Methoden der FritzBox-Klasse definiert werden
        self.dsl_setup_init()
        self.checkbox_fehlerdaten_dialog()
        if not self.skip_configuration():
            self.dsl_setup_wizard()
        self.neue_firmware_dialog() # Neue Firmware-Dialog-Behandlung hinzugefügt


    def reset_fritzbox_via_forgot_password(self):
        """Leitet den Werksreset über den 'Passwort vergessen'-Link ein (ohne Login)."""
        if not self.warte_auf_erreichbarkeit():
            raise Exception("FritzBox nicht erreichbar für Reset.")
        print("🚨 Werkseinstellungen einleiten (via 'Passwort vergessen')...")
        self.browser.get_url(self.url)

        kandidaten = [
            '//*[@id="dialogFoot"]/a',
            '//a[contains(text(), "Passwort vergessen")]',
            '//button[contains(text(), "Passwort vergessen")]',
        ]

        for xpath in kandidaten:
            try:
                self.browser.klicken(xpath)
                print(f"🔁 Reset-Link gefunden ({xpath})")
                break
            except:
                continue
        else:
            raise Exception("❌ Kein Reset-Link gefunden.")

        self.browser.klicken('//*[@id="sendFacReset"]')
        print("🔁 Reset ausgelöst, warte auf Neustart...")
        time.sleep(50)
        self.is_reset = True # Zustand der Box aktualisieren

    def checkbox_fehlerdaten_dialog(self):
        """Behandelt den Fehlerdaten-Senden-Dialog."""
        print("🛑 Fehlerdaten-Checkbox prüfen...")
        try:
            checkbox = self.browser.sicher_warten('//*[@id="uiTr069diag"]', timeout=5)
            if checkbox.is_selected():
                checkbox.click()
                print("☑️ Deaktiviert.")
            else:
                print("☑️ Bereits deaktiviert.")
        except Exception: # Generische Exception, da es auch einfach nicht da sein könnte
            print("ℹ️ Keine Checkbox gefunden.")
            return

        try:
            self.browser.klicken('//*[@id="uiApply"]')
            print("➡️ Übernommen.")
        except Exception:
            pass # Button nicht da oder schon geklickt

    def wlan_antenne_check(self, max_versuche=2):
        """Prüft die WLAN-Antennen und Signalstärke."""
        print("📡 WLAN-Antennen prüfen...")

        for versuch in range(1, max_versuche + 1):
            try:
                self.browser.klicken('//*[@id="wlan"]')
                time.sleep(1)
                self.browser.klicken('//*[@id="chan"]')
                time.sleep(5)

                rows = self.browser.driver.find_elements(By.XPATH, '//div[@class="flexRow" and .//div[@prefid="rssi"]]')
                if rows:
                    print(f"📶 {len(rows)} Netzwerke gefunden. Verarbeite...")
                    break
                else:
                    print(f"⚠️ Kein WLAN gefunden (Versuch {versuch}/{max_versuche}).")
            except Exception as e:
                print(f"❌ Fehler beim Zugriff auf WLAN-Liste (Versuch {versuch}): {e}")
                rows = []

            if versuch < max_versuche:
                print("🔁 Neuer Versuch in 5 Sekunden...")
                time.sleep(5)
            else:
                raise Exception("❌ Auch nach mehreren Versuchen keine Netzwerke gefunden.")

        print("\n📋 Ergebnisübersicht:\n")
        for i in range(len(rows)):
            try:
                row_xpath = f'(//div[@class="flexRow" and .//div[@prefid="rssi"]])[{i + 1}]'
                row = self.browser.driver.find_element(By.XPATH, row_xpath)

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
        self.is_wifi_checked = True

    def firmware_update(self, path):
        """Führt ein Firmware-Update durch."""
        print("🆙 Firmware-Update...")
        self.browser.klicken('//*[@id="sys"]')
        self.browser.klicken('//*[@id="mUp"]')
        self.browser.klicken('//*[@id="userUp"]')

        try:
            checkbox = self.browser.sicher_warten('//*[@id="uiExportCheck"]', timeout=10)
            if checkbox.is_selected():
                checkbox.click()
        except:
            pass

        self.browser.schreiben('//*[@id="uiFile"]', path)
        self.browser.klicken('//*[@id="uiUpdate"]')
        print("📤 Firmware wird hochgeladen...")

        try:
            self.browser.sicher_warten('//*[@id="submitLoginBtn"]', timeout=300)
            print("✅ Update abgeschlossen.")
        except:
            print("⚠️ Kein Redirect erkannt – versuche manuell.")
            if self.warte_auf_erreichbarkeit():
                self.browser.get_url(self.url)

    def get_firmware_version(self):
        """Ermittelt die aktuelle Firmware-Version."""
        print("ℹ️ Ermittle Firmware-Version...")
        try:
            self.browser.klicken('//*[@id="sys"]')
            self.browser.klicken('//*[@id="mUp"]')
            version_elem = self.browser.sicher_warten('//*[@class="fakeTextInput"]')
            version_text = version_elem.text.strip()

            if version_text:
                self.os_version = version_text
                print(f"✅ Firmware-Version: {self.os_version}")
                return self.os_version
            else:
                print("❌ Keine Version gefunden.")
                return None
        except Exception as e:
            print(f"❌ Fehler beim Ermitteln der Firmware-Version: {e}")
            return None

    def get_box_model(self):
        """Versucht, das Fritzbox-Modell zu ermitteln."""
        print("🔍 Ermittle Box-Modell...")
        try:
            # Beispiel: Modellinfo könnte auf der Übersichtsseite sein oder in den Systeminfos
            # Dies ist ein Platzhalter, da die genauen XPATHs je nach Firmware variieren können
            # Du müsstest hier die spezifischen XPATHs für die 7590, 7530, 6890 etc. einfügen.
            # Oder, falls es einen allgemeinen Weg gibt, z.B. über die "System" -> "Update" Seite,
            # wo oft Modell und Version zusammen stehen.
            self.browser.get_url(self.url + "/system/info.lua") # Beispiel-URL, muss angepasst werden
            model_elem = self.browser.sicher_warten('//div[@class="boxTitle"] | //h1', timeout=5) # Beispiel-XPATH
            model_text = model_elem.text.strip()
            if "FRITZ!Box" in model_text:
                self.box_model = model_text.split("FRITZ!Box")[-1].strip()
                print(f"✅ Box-Modell: {self.box_model}")
                return self.box_model
            else:
                print("⚠️ Modell konnte nicht eindeutig identifiziert werden.")
                return None
        except Exception as e:
            print(f"❌ Fehler beim Ermitteln des Box-Modells: {e}")
            return None

    def dsl_setup_init(self):
        """Behandelt initialen DSL-Setup-Dialog."""
        print("⚙️ Setze default DSL-Settings...")
        try:
            self.browser.sicher_warten('//*[@id="uiForward"]')
        except Exception:
            print("DSL-Setup nicht aufrufbar oder nicht vorhanden.")
            return

        for xpath in ['//*[@id="uiForward"]', '//*[@id="uiForward"]']:
            try:
                self.browser.klicken(xpath)
                time.sleep(2)
            except Exception:
                print(f"⚠️ Scheinbar kein DSL-Init notwendig oder Klick fehlgeschlagen für {xpath}.")
                return

    def neue_firmware_dialog(self):
        """Behandelt den Dialog nach einer neuen Firmware-Installation."""
        print("Prüfe ob neue Firmware-installiert wurde.")
        try:
            self.browser.sicher_warten('//a[contains(text(), "OK")]', timeout=5)
        except Exception:
            print("Keine neue FW installiert.")
            return

        for xpath in ['//a[contains(text(), "Weiter")]', '//a[contains(text(), "OK")]']:
            try:
                self.browser.klicken(xpath)
                time.sleep(2)
            except Exception:
                print(f"⚠️ Scheinbar kein Dialog für neue FW notwendig oder Klick fehlgeschlagen für {xpath}.")
                return

    def dsl_setup_wizard(self):
        """Durchläuft den DSL-Setup-Wizard."""
        print("⚙️ Setup-Wizard komplett durchlaufen (DSL)...")
        try:
            self.browser.klicken('//*[@id="dlg_welcome"]/p[3]/a') # Direkter Link zum Überspringen
        except:
            print("⚠️ Kein Direktlink – manueller Ablauf des Wizards.")
            for xpath in [
                '//*[@id="uiForward"]', '//*[@id="uiSkip"]', '//*[@id="uiSkip"]',
                '//*[@id="uiWizFooterBtns"]/button', '//*[@id="uiWizFooterBtns"]/button',
                '//*[@id="uiWizFooterBtns"]/button', '//*[@id="uiFinish"]',
                '//*[@id="Button1"]'
            ]:
                try:
                    self.browser.klicken(xpath)
                    time.sleep(2)
                except Exception:
                    print(f"⚠️ Wizard-Fehler bei {xpath}\n DSL Wizzard geschlossen.")
                    return # Wenn ein Klick fehlschlägt, ist der Wizard wahrscheinlich weg

    def factory_reset_from_ui(self):
        """Setzt die FritzBox über die Benutzeroberfläche auf Werkseinstellungen zurück."""
        print("🚨 Werkseinstellungen (aus der Oberfläche)...")

        try:
            # Nur auf "System" klicken, wenn "mSave" NICHT da ist
            try:
                self.browser.sicher_warten('//*[@id="mSave"]', timeout=5)
                print("✅ Menü bereits offen – kein Klick auf 'System' nötig.")
            except:
                print("📂 Öffne 'System'-Menü...")
                self.browser.klicken('//*[@id="sys"]')
                time.sleep(1)

            for xpath in [
                '//*[@id="mSave"]',      # Sicherung
                '//*[@id="default"]',    # Werkseinstellungen
                '//*[@id="content"]/div/button', # Übernehmen-Button
                '//*[@id="Button1"]'     # OK-Button (im Bestätigungsdialog)
            ]:
                try:
                    self.browser.klicken(xpath)
                    time.sleep(3)
                except Exception as e:
                    print(f"⚠️ Fehler bei Reset-Klick: {xpath} – {e}. Versuche nächsten Schritt.")
        except Exception as e:
            print(f"❌ Fehler im Reset-Ablauf: {e}")
            raise # Fehler weitergeben, wenn der Hauptablauf gestört ist

        print("⚠️ℹ️⚠️ Bitte jetzt physischen Knopf an der Box drücken (falls erforderlich)...")

        try:
            def finde_und_klicke_ok(driver_instance): # driver_instance hier ist self.browser.driver
                for btn in driver_instance.find_elements(By.ID, "Button1"):
                    if "OK" in btn.text:
                        btn.click()
                        return True
                return False

            WebDriverWait(self.browser.driver, 180).until(finde_und_klicke_ok)
            print("✅ OK-Button geklickt.")
        except Exception as e:
            print(f"❌ Fehler bei OK-Klick nach physischer Bestätigung: {e}")
            raise Exception("Fehler beim Bestätigen des Werkseinstellungsresets.")

        time.sleep(25)
        if self.ist_sprachauswahl():
            print("✅ Erfolgreich auf Werkseinstellungen zurückgesetzt.")
            self.is_reset = True
        else:
            print("⚠️ Nicht verifiziert – bitte manuell prüfen, ob Reset erfolgreich war.")

    def _select_firmware_path_manually(self):
        """Öffnet einen Dateidialog zur manuellen Auswahl des Firmware-Pfades."""
        root = tk.Tk()
        root.withdraw()
        file_path = filedialog.askopenfilename(title="Firmware-Datei auswählen",
                                               filetypes=[("Firmware Image", "*.image")])
        root.destroy()  # Tkinter-Fenster schließen
        return file_path

    def handle_firmware_or_reset(self):
        """
        Entscheidet, ob ein Firmware-Update oder Reset nötig ist, basierend auf der Version
        und versucht, den Firmware-Pfad automatisch zu finden.
        """
        firmware_mapping = {
            "7590": "8.03",
            "7530": "8.02",
            "6890_LTE": "7.57",
        }

        # Zuerst das Box-Modell ermitteln
        if not self.box_model:
            self.get_box_model()

        current_version = self.get_firmware_version()
        target_version = firmware_mapping.get(self.box_model)

        firmware_path_auto = None
        if self.box_model and target_version:
            # Den aktuellen Ausführungspfad ermitteln
            current_dir = Path(__file__).parent
            # Beispielpfad-Erstellung
            firmware_filename = f"FRITZ.Box_{self.box_model}-{target_version}.image"
            firmware_path_auto = current_dir / "firmware und recovery" / firmware_filename

            print(f"ℹ️ Versuche automatischen Firmware-Pfad: {firmware_path_auto}")
            if firmware_path_auto.is_file():
                print(f"✅ Firmware-Datei gefunden: {firmware_path_auto}")
            else:
                print(f"❌ Firmware-Datei nicht gefunden unter {firmware_path_auto}.")
                firmware_path_auto = None  # Setze auf None, um den Fallback zu triggern

        firmware_to_use = firmware_path_auto

        # Fallback auf manuellen Selector, wenn die Datei nicht gefunden wurde oder Modell/Version unbekannt
        if not firmware_to_use:
            print(
                "⚠️ Automatische Firmware-Erkennung fehlgeschlagen oder Datei nicht gefunden. Bitte manuell auswählen.")
            firmware_to_use = self._select_firmware_path_manually()
            if not firmware_to_use:
                print("❌ Keine Firmware-Datei ausgewählt. Kann nicht fortfahren.")
                return

        # Logik für Update oder Reset
        if self.box_model and target_version and current_version != target_version:
            print(f"Firmware {self.box_model} sollte auf {target_version} sein. Aktuell: {current_version}")
            self.firmware_update(firmware_to_use)
        elif current_version == "8.03":  # Dies ist die TIM-Spezifische Logik, die beibehalten werden soll
            print("🔁 Version 8.03 erkannt – Reset statt Update (TIM-Spezifisch).")
            self.factory_reset_from_ui()
        else:
            print(
                f"ℹ️ Firmware ist aktuell ({current_version}) oder kein spezifisches Update für {self.box_model} nötig.")
            # Hier könntest du optional einen Reset triggern, wenn kein Update nötig ist, aber ein Reset gewünscht ist.
            # z.B. self.factory_reset_from_ui()

    def skip_configuration(self):
        """Versucht, den Konfigurationsdialog zu überspringen."""
        print("📌 Konfigurationsdialog überspringen...")
        try:
            for _ in range(2):
                placeholder_elem = WebDriverWait(self.browser.driver, 5).until(
                    EC.presence_of_element_located((By.XPATH, '//*[@id="Button1"]'))
                )
                if placeholder_elem:
                    placeholder_elem.click()
                    print("✅ Platzhalter-Button gedrückt.")
                    time.sleep(2)
        except Exception:
            print("ℹ️ Kein Konfigurationsdialog erkannt oder Timeout.")
            return False
        return True