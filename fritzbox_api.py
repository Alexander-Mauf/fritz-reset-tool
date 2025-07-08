# fritzbox_api.py
import time
import requests
import os
from pathlib import Path
import tkinter as tk
from tkinter import filedialog
import re # Für die verbesserte Modell-Erkennung

# Da Browser jetzt eine eigene Klasse ist, importieren wir sie:
from browser_utils import Browser
from selenium.webdriver.common.by import By # Immer noch für By.XPATH nötig
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


FRITZ_DEFAULT_URL = "http://fritz.box"

class FirmwareManager:
    """Verwaltet Firmware-Dateien und deren Pfade basierend auf dem FritzBox-Modell."""

    def __init__(self):
        # Mapping der Box-Modelle zu ihren Ziel-Firmware-Versionen
        self.firmware_mapping = {
            "7590": "8.03",
            "7530": "8.02",
            "6890_LTE": "7.57", # Beispiel für spezielle Modelle
            # Füge hier weitere Modelle und deren Zielversionen hinzu
        }

    def _select_firmware_path_manually(self):
        """Öffnet einen Dateidialog zur manuellen Auswahl des Firmware-Pfades."""
        root = tk.Tk()
        root.withdraw() # Versteckt das Hauptfenster
        file_path = filedialog.askopenfilename(
            title="Firmware-Datei auswählen",
            filetypes=[("Firmware Image", "*.image")]
        )
        root.destroy() # Tkinter-Fenster schließen
        return file_path

    def get_firmware_path(self, box_model: str) -> str | None:
        """
        Versucht, den Firmware-Pfad automatisch zu finden.
        Fällt auf einen manuellen Dateidialog zurück, wenn die Datei nicht gefunden wird.
        """
        if not box_model:
            print("⚠️ Box-Modell ist unbekannt. Firmware-Pfad kann nicht automatisch ermittelt werden.")
            return self._select_firmware_path_manually()

        target_version = self.firmware_mapping.get(box_model)
        if not target_version:
            print(f"⚠️ Keine Ziel-Firmware-Version für Modell '{box_model}' bekannt. Bitte manuell auswählen.")
            return self._select_firmware_path_manually()

        current_dir = Path(__file__).parent # Der Pfad, in dem sich fritzbox_api.py befindet
        firmware_filename = f"FRITZ.Box_{box_model}-{target_version}.image"
        firmware_path_auto = current_dir / "firmware und recovery" / firmware_filename

        print(f"ℹ️ Versuche automatischen Firmware-Pfad für {box_model} (Ziel: {target_version}): {firmware_path_auto}")

        if firmware_path_auto.is_file():
            print(f"✅ Firmware-Datei gefunden: {firmware_path_auto}")
            return str(firmware_path_auto) # Gib den String-Pfad zurück
        else:
            print(f"❌ Firmware-Datei nicht gefunden unter {firmware_path_auto}.")
            print("⚠️ Fällt auf manuelle Auswahl zurück.")
            return self._select_firmware_path_manually()


class FritzBox:
    """Repräsentiert eine FritzBox und kapselt ihre Interaktionen."""

    def __init__(self, browser: Browser):
        if not isinstance(browser, Browser):
            raise TypeError("Der übergebene Browser muss eine Instanz der Browser-Klasse sein.")
        self.browser = browser
        self.url = FRITZ_DEFAULT_URL
        self.os_version = None
        self.is_reset = False
        self.language = None
        self.is_logged_in = False
        self.password = None # Wird nach dem ersten Login gesetzt
        self.box_model = None
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
                    # requests.get ist hier besser, da es schneller und ressourcenschonender ist als Selenium
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

    def _check_if_login_required(self):
        """Interne Methode: Prüft, ob das Passwortfeld auf der aktuellen Seite vorhanden ist."""
        try:
            # Hier direkt den WebDriver des Browser-Objekts verwenden
            return bool(self.browser.driver.find_elements(By.XPATH, '//input[@id="uiPass" or @type="password"]'))
        except Exception:
            return False

    def _handle_language_selection(self):
        """Interne Methode: Behandelt die Sprachauswahl, falls sie erscheint."""
        try:
            self.browser.get_url(self.url) # Sicherstellen, dass wir auf der Login-Seite sind
            # Prüfe, ob Sprachauswahl-Elemente da sind
            if self.browser.sicher_warten('//*[@id="uiLanguage-en"]', timeout=3, sichtbar=False):
                print("🌐 Sprachauswahl erkannt. Setze auf Englisch...")
                self.browser.klicken('//*[@id="uiLanguage-en"]') # Versuche Englisch
                self.browser.klicken('//*[@id="submitLangBtn"]')
                time.sleep(3) # Kurze Wartezeit nach Sprachauswahl
                self.language = "en"
                return True
        except Exception:
            print("ℹ️ Keine Sprachauswahl erkannt oder konnte nicht verarbeitet werden.")
        return False

    def is_main_menu_loaded_and_ready(self, timeout=5):
        """
        Prüft, ob die Hauptmenüstruktur der FritzBox geladen und interaktiv ist.
        Sucht nach Schlüssel-Menüpunkten wie WLAN, System etc.
        """
        menu_xpaths = [
            '//*[@id="wlan"]',  # WLAN Menüpunkt
            '//*[@id="sys"]',  # System Menüpunkt
            '//*[@id="internet"]',  # Internet Menüpunkt
            '//*[@id="home"]',  # Heimnetz Menüpunkt
            # Füge hier weitere robuste XPATHs für Hauptmenüpunkte hinzu
        ]
        print(f"🔍 Prüfe auf geladenes und klickbares Hauptmenü (Timeout: {timeout}s)...")
        for xpath in menu_xpaths:
            try:
                # Versuche, das Element zu finden UND zu prüfen, ob es klickbar ist (sichtbar & enabled)
                element = self.browser.sicher_warten(xpath, timeout=timeout / len(menu_xpaths), sichtbar=True)
                if element and element.is_displayed() and element.is_enabled():
                    print(f"✅ Hauptmenü-Element '{xpath}' gefunden und bereit.")
                    return True
            except Exception:
                pass  # Element nicht gefunden oder nicht bereit, versuche nächstes
        print("❌ Hauptmenü nicht gefunden oder nicht bereit.")
        return False

    def login(self, password: str, force_reload=False) -> bool:
        """
        Führt den Login in die FritzBox durch.
        Versucht, vorhandenen Login zu erkennen und Dialoge zu behandeln.
        Gibt True bei Erfolg, False bei Fehlschlag zurück.
        """
        if not self.warte_auf_erreichbarkeit():
            print("❌ FritzBox nicht erreichbar für Login.")
            return False

        self.password = password # Speichere das Passwort für potenzielle Re-Logins

        print("🔐 Login wird versucht...")

        # NEU: Schnellprüfung, ob bereits eingeloggt und Hauptmenü bereit ist
        if not force_reload and self.is_main_menu_loaded_and_ready(timeout=5):
            print("✅ Bereits eingeloggt und Hauptmenü bereit.")
            self.is_logged_in = True
            return True

        # Wenn nicht eingeloggt oder force_reload, dann weiter mit dem eigentlichen Login-Prozess
        self.browser.get_url(self.url)

        # Prüfe auf Sprachauswahl zuerst
        if self._handle_language_selection():
            self.browser.get_url(self.url) # Nach Sprachauswahl ggf. neu laden

        # Prüfen, ob Login-Feld überhaupt sichtbar ist (oder ob wir auf einer anderen Seite sind)
        def _check_if_login_required(self) -> bool:
            """Interne Methode: Prüft, ob das Passwortfeld auf der aktuellen Seite vorhanden ist."""
            try:
                # Hier direkt den WebDriver des Browser-Objekts verwenden
                # Timeout kurz halten, da es nur eine schnelle Prüfung ist
                return bool(
                    self.browser.sicher_warten('//*[@id="uiPass" or @type="password"]', timeout=2, sichtbar=False))
            except Exception:
                return False

        # Wenn wir hier sind, ist das Login-Feld vermutlich da und ein Login wird benötigt.
        try:
            if not self.browser.schreiben('//*[@id="uiPass"]', password):
                raise Exception("Passwort konnte nicht in Feld geschrieben werden.")
            if not self.browser.klicken('//*[@id="submitLoginBtn"]'):
                raise Exception("Login-Button konnte nicht geklickt werden.")

            # NEU: Warte auf das Hauptmenü als primäre Login-Bestätigung
            if not self.is_main_menu_loaded_and_ready(timeout=15): # Längeres Timeout für ersten Login
                raise Exception("Hauptmenü nach Login nicht geladen oder nicht bereit.")

            print("✅ Login erfolgreich und Hauptmenü zugänglich.")
            self.is_logged_in = True
            self._handle_post_login_dialogs() # Dialoge nach dem Login behandeln
            return True
        except Exception as e:
            print(f"❌ Login fehlgeschlagen: {e}")
            self.is_logged_in = False
            return False

    def _handle_post_login_dialogs(self):
        """Behandelt Dialoge, die direkt nach dem Login erscheinen können."""
        print("⚙️ Bearbeite Post-Login-Dialoge...")
        # Reihenfolge ist wichtig, da einige Dialoge andere beeinflussen
        self.neue_firmware_dialog()
        self.dsl_setup_init()
        self.checkbox_fehlerdaten_dialog()
        # skip_configuration sollte als letztes, da es generische "Weiter"-Buttons klickt
        self.skip_configuration()


    def reset_via_forgot_password(self):
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

        found_reset_link = False
        for xpath in kandidaten:
            if self.browser.klicken(xpath):
                print(f"🔁 Reset-Link gefunden und geklickt ({xpath})")
                found_reset_link = True
                break
        if not found_reset_link:
            raise Exception("❌ Kein Reset-Link gefunden.")

        # Bestätigung des Resets
        if self.browser.klicken('//*[@id="sendFacReset"]'):
            print("🔁 Reset ausgelöst, warte auf Neustart...")
            time.sleep(60) # Erhöht, da ein Reset länger dauern kann
            self.is_reset = True
            # Nach einem Reset ist ein erneuter Check auf Erreichbarkeit und Sprachauswahl sinnvoll
            if self.ist_sprachauswahl():
                print("✅ FritzBox erfolgreich auf Werkseinstellungen zurückgesetzt und Sprachauswahl erreicht.")
                return True
            else:
                print("⚠️ Reset ausgelöst, aber Sprachauswahl nicht verifiziert. Bitte manuell prüfen.")
                return False
        else:
            print("❌ Fehler beim Bestätigen des Resets via 'sendFacReset'.")
            return False


    def perform_factory_reset_from_ui(self):
        """Setzt die FritzBox über die Benutzeroberfläche auf Werkseinstellungen zurück (nach Login)."""
        if not self.is_logged_in:
            print("❌ Nicht eingeloggt. Login für UI-Reset erforderlich.")
            raise Exception("Login für UI-Reset erforderlich.")

        print("🚨 Werkseinstellungen (aus der Oberfläche)...")

        try:
            # Navigiere zu System -> Sicherung
            if not self.browser.klicken('//*[@id="sys"]'):
                raise Exception("Konnte nicht auf 'System' klicken.")
            time.sleep(1)
            if not self.browser.klicken('//*[@id="mSave"]'):
                raise Exception("Konnte nicht auf 'Sicherung' klicken.")
            time.sleep(1)

            # Klicke auf 'Werkseinstellungen'
            if not self.browser.klicken('//*[@id="default"]'):
                raise Exception("Konnte nicht auf 'Werkseinstellungen' klicken.")
            time.sleep(1)

            # Bestätigung 'Wiederherstellen' (oder ähnlicher Button)
            if not self.browser.klicken('//*[@id="content"]/div/button'):
                raise Exception("Konnte nicht auf den Bestätigungsbutton klicken (z.B. 'Wiederherstellen').")
            time.sleep(3)

        except Exception as e:
            print(f"❌ Fehler im Reset-Ablauf über UI-Menü: {e}")
            raise # Fehler weitergeben, wenn der Hauptablauf gestört ist

        print("⚠️ℹ️⚠️ Bitte jetzt physischen Knopf an der Box drücken (falls erforderlich)...")

        try:
            # Warte auf OK-Button nach physischer Bestätigung
            # Die Funktion muss hier auf self.browser.driver zugreifen
            def finde_und_klicke_ok_button(driver_instance):
                for btn in driver_instance.find_elements(By.ID, "Button1"):
                    if "OK" in btn.text or "ok" in btn.text.lower(): # Case-insensitive check
                        btn.click()
                        return True
                return False

            WebDriverWait(self.browser.driver, 180).until(finde_und_klicke_ok_button)
            print("✅ OK-Button geklickt nach physischer Bestätigung.")
            self.is_reset = True
            time.sleep(25) # Wartezeit nach Reset
            if self.ist_sprachauswahl():
                print("✅ Erfolgreich auf Werkseinstellungen zurückgesetzt.")
                return True
            else:
                print("⚠️ Nicht verifiziert – bitte manuell prüfen.")
                return False
        except Exception as e:
            print(f"❌ Fehler bei OK-Klick nach physischer Bestätigung: {e}")
            raise Exception("Fehler beim Bestätigen des Werkseinstellungsresets.")

    def checkbox_fehlerdaten_dialog(self):
        """Behandelt den Fehlerdaten-Senden-Dialog."""
        print("🛑 Fehlerdaten-Checkbox prüfen...")
        try:
            # Sicher warten auf die Checkbox
            checkbox = self.browser.sicher_warten('//*[@id="uiTr069diag"]', timeout=5)
            if checkbox.is_selected():
                checkbox.click()
                print("☑️ Deaktiviert.")
            else:
                print("☑️ Bereits deaktiviert.")
            # Klicke auf den Übernehmen-Button, falls vorhanden
            self.browser.klicken('//*[@id="uiApply"]')
            print("➡️ Änderungen übernommen (Fehlerdaten).")
            return True
        except Exception:
            print("ℹ️ Keine Fehlerdaten-Checkbox oder Übernehmen-Button gefunden/benötigt.")
            return False

    def check_wlan_antennas(self, max_versuche=2):
        """Prüft die WLAN-Antennen und Signalstärke."""
        print("📡 WLAN-Antennen prüfen...")
        self.is_wifi_checked = False # Reset des Status vor dem Check

        for versuch in range(1, max_versuche + 1):
            try:
                if not self.browser.klicken('//*[@id="wlan"]'):
                    raise Exception("Konnte nicht auf 'WLAN' klicken.")
                time.sleep(1)
                if not self.browser.klicken('//*[@id="chan"]'):
                    raise Exception("Konnte nicht auf 'Funkkanal' klicken.")
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
        if not rows:
            print("Keine WLAN-Netzwerke zur Analyse gefunden.")
            return False

        for i in range(len(rows)):
            try:
                # Frisch halten: jedes Row-Element im Loop neu holen
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
                print(f"⚠️ Fehler beim Verarbeiten eines Netzwerks (#{i+1}): {e}")
        self.is_wifi_checked = True
        return True


    def perform_firmware_update(self, firmware_path: str):
        """Führt ein Firmware-Update mit der angegebenen Datei durch."""
        if not firmware_path or not Path(firmware_path).is_file():
            raise ValueError(f"Ungültiger Firmware-Pfad: {firmware_path}")
        if not self.is_logged_in:
            print("❌ Nicht eingeloggt. Login für Firmware-Update erforderlich.")
            raise Exception("Login für Firmware-Update erforderlich.")

        print(f"🆙 Starte Firmware-Update mit Datei: {firmware_path}")

        try:
            # Navigiere zu System -> Update
            if not self.browser.klicken('//*[@id="sys"]'):
                raise Exception("Konnte nicht auf 'System' klicken.")
            if not self.browser.klicken('//*[@id="mUp"]'):
                raise Exception("Konnte nicht auf 'Update' klicken.")
            # Gehe zum manuellen Update-Tab
            if not self.browser.klicken('//*[@id="userUp"]'):
                raise Exception("Konnte nicht auf 'Firmware-Update' Tab klicken.")

            # Versuche, die Export-Checkbox zu deaktivieren (falls vorhanden)
            try:
                checkbox = self.browser.sicher_warten('//*[@id="uiExportCheck"]', timeout=5)
                if checkbox.is_selected():
                    checkbox.click()
                    print("☑️ 'Einstellungen sichern'-Checkbox deaktiviert.")
            except Exception:
                print("ℹ️ 'Einstellungen sichern'-Checkbox nicht gefunden oder nicht aktiv.")
                pass # Ist optional

            # Pfad zur Firmware-Datei eingeben
            if not self.browser.schreiben('//*[@id="uiFile"]', firmware_path):
                raise Exception(f"Konnte Firmware-Pfad {firmware_path} nicht eingeben.")
            time.sleep(1) # Kurze Pause, damit das Feld reagiert

            # Update starten
            if not self.browser.klicken('//*[@id="uiUpdate"]'):
                raise Exception("Konnte nicht auf 'Update starten' klicken.")
            print("📤 Firmware wird hochgeladen und Update gestartet...")

            # Warte auf den Abschluss des Updates (Rückkehr zum Login-Screen oder ähnliches)
            # Kann sehr lange dauern, daher hohes Timeout
            try:
                WebDriverWait(self.browser.driver, 400).until(
                    EC.presence_of_element_located((By.ID, "uiPass")) # Zurück zum Login-Feld
                    # Oder ein anderes eindeutiges Element, das nach dem Neustart erscheint (z.B. Sprachauswahl)
                )
                print("✅ Firmware-Update abgeschlossen und FritzBox neu gestartet.")
                self.is_logged_in = False # Nach Update ist man ausgeloggt
                self.os_version = None # Version muss neu ermittelt werden
                return True
            except Exception:
                print("⚠️ Update-Abschluss nicht automatisch erkannt (Timeout). Versuche manuell zu prüfen.")
                if self.warte_auf_erreichbarkeit():
                    self.browser.get_url(self.url) # Versuch, die Seite neu zu laden
                    return True # Gehe davon aus, dass es geklappt hat
                return False

        except Exception as e:
            print(f"❌ Fehler während des Firmware-Updates: {e}")
            raise # Fehler weitergeben


    def get_firmware_version(self):
        """Ermittelt die aktuelle Firmware-Version der FritzBox."""
        print("ℹ️ Ermittle Firmware-Version...")
        try:
            # Navigiere zu System -> Update
            if not self.browser.klicken('//*[@id="sys"]'):
                print("Konnte nicht auf 'System' klicken für Versionsprüfung.")
                return None
            if not self.browser.klicken('//*[@id="mUp"]'):
                print("Konnte nicht auf 'Update' klicken für Versionsprüfung.")
                return None

            # Die Version steht oft in einem Textfeld/Label auf dieser Seite
            version_elem = self.browser.sicher_warten('//*[@class="fakeTextInput" or contains(@class, "version_text")]', timeout=10)
            version_text = version_elem.text.strip()

            if version_text:
                self.os_version = version_text
                print(f"✅ Firmware-Version: {self.os_version}")
                return self.os_version
            else:
                print("❌ Keine Firmware-Version gefunden auf der Update-Seite.")
                return None
        except Exception as e:
            print(f"❌ Fehler beim Ermitteln der Firmware-Version: {e}")
            return None

    def get_box_model(self):
        """Versucht, das Fritzbox-Modell zu ermitteln."""
        print("🔍 Ermittle Box-Modell...")
        try:
            # Gehe zur Übersichtsseite, wo Modell-Infos oft sichtbar sind
            self.browser.get_url(self.url + "/overview") # Dies ist eine häufige URL für die Übersicht
            time.sleep(2)

            # Versuche verschiedene XPATHs, um das Modell zu finden
            model_xpaths = [
                '//h1[contains(text(), "FRITZ!Box")]', # Häufig im Titel
                '//span[@class="version" and contains(text(), "FRITZ!Box")]', # AVM-spezifische Klasse
                '//div[@class="boxInfo"]/span[contains(text(), "FRITZ!Box")]',
                '//*[contains(@class, "deviceTitle")] | //*[contains(@class, "productname")]' # Generischere Selektoren
            ]
            for xpath in model_xpaths:
                try:
                    model_elem = self.browser.sicher_warten(xpath, timeout=3)
                    model_text = model_elem.text.strip()
                    if "FRITZ!Box" in model_text:
                        # Extrahiere nur die Modellnummer (z.B. "7590" aus "FRITZ!Box 7590")
                        match = re.search(r'FRITZ!Box (\d{4,}(?: ?LTE)?)', model_text) # Erweitert für "6890 LTE"
                        if match:
                            model_number = match.group(1).replace(" ", "_").strip() # z.B. "6890_LTE"
                            self.box_model = model_number
                            print(f"✅ Box-Modell: {self.box_model}")
                            return self.box_model
                except Exception:
                    pass # Versuche den nächsten XPath

            print("⚠️ Modell konnte nicht eindeutig identifiziert werden. Keine spezifische FRITZ!Box Modellnummer gefunden.")
            self.box_model = "UNKNOWN" # Setze auf UNKNOWN, um Loop zu vermeiden
            return None
        except Exception as e:
            print(f"❌ Fehler beim Ermitteln des Box-Modells: {e}")
            self.box_model = "UNKNOWN"
            return None

    def dsl_setup_init(self):
        """Behandelt initialen DSL-Setup-Dialog (z.B. nach einem Reset)."""
        print("⚙️ Prüfe auf und setze default DSL-Settings (falls vorhanden)...")
        try:
            # Versuche, den 'Weiter'-Button zu finden, der das Initial-Setup einleitet
            if self.browser.klicken('//*[@id="uiForward"]', timeout=5):
                print("✅ 'Weiter'-Button im DSL-Setup initial gefunden und geklickt.")
                time.sleep(2)
                # Manchmal muss man zweimal klicken
                self.browser.klicken('//*[@id="uiForward"]', timeout=3)
                return True
            else:
                print("ℹ️ Kein initialer DSL-Setup-Dialog ('uiForward') gefunden.")
                return False
        except Exception as e:
            print(f"⚠️ Fehler beim initialen DSL-Setup-Check: {e}")
            return False

    def neue_firmware_dialog(self):
        """Behandelt den Dialog, der nach einer Firmware-Installation erscheinen kann."""
        print("Prüfe ob 'Neue Firmware installiert'-Dialog erscheint...")
        try:
            # Es gibt oft einen "OK" oder "Weiter" Button
            if self.browser.klicken('//a[contains(text(), "OK")]', timeout=5):
                print("✅ 'OK' Button im Firmware-Dialog geklickt.")
                time.sleep(2)
                return True
            elif self.browser.klicken('//a[contains(text(), "Weiter")]', timeout=5):
                print("✅ 'Weiter' Button im Firmware-Dialog geklickt.")
                time.sleep(2)
                return True
            else:
                print("ℹ️ Kein 'Neue Firmware installiert'-Dialog gefunden.")
                return False
        except Exception as e:
            print(f"⚠️ Fehler beim Behandeln des Firmware-Dialogs: {e}")
            return False

    def dsl_setup_wizard(self):
        """Durchläuft den DSL-Setup-Wizard (falls er nach einem Reset/Update erscheint)."""
        print("⚙️ Prüfe auf und durchlaufe Setup-Wizard (DSL)...")
        try:
            # Versuche zuerst, den Direktlink zum Überspringen zu finden/klicken
            if self.browser.klicken('//*[@id="dlg_welcome"]/p[3]/a', timeout=5):
                print("✅ Direktlink zum Überspringen des Wizards gefunden und geklickt.")
                time.sleep(2)
                return True
            else:
                print("⚠️ Kein Direktlink zum Überspringen – versuche manuellen Ablauf des Wizards.")
                # Wenn kein Direktlink, klicke dich durch die Schritte
                wizard_xpaths = [
                    '//*[@id="uiForward"]',
                    '//*[@id="uiSkip"]',
                    '//*[@id="uiWizFooterBtns"]/button', # Generic "Weiter" button
                    '//*[@id="uiFinish"]',
                    '//*[@id="Button1"]' # Generic "OK" button
                ]
                for xpath in wizard_xpaths:
                    try:
                        if self.browser.klicken(xpath, timeout=5):
                            print(f"➡️ Wizard-Schritt mit {xpath} geklickt.")
                            time.sleep(2)
                        else:
                            # Wenn ein Klick fehlschlägt, ist der Wizard wahrscheinlich beendet oder nicht aktiv.
                            print(f"ℹ️ Wizard-Schritt {xpath} nicht gefunden oder Wizard beendet.")
                            return True # Workflow fortsetzen
                    except Exception:
                        print(f"⚠️ Fehler oder Element {xpath} im Wizard nicht gefunden. Wizard beendet.")
                        return True # Vermutlich durchgelaufen oder nicht mehr da

        except Exception as e:
            print(f"❌ Schwerwiegender Fehler im DSL-Setup-Wizard: {e}")
            return False

    def skip_configuration(self):
        """Versucht, generische Konfigurationsdialoge zu überspringen (z.B. "Weiter"-Buttons)."""
        print("📌 Konfigurationsdialoge überspringen (generisch)...")
        # Versuche mehrere generische "Weiter"-Buttons zu klicken, die nach einem Login/Reset erscheinen könnten
        generic_buttons = [
            '//*[@id="Button1"]', # AVM Standard-Button ID
            '//button[contains(text(), "Weiter")]',
            '//a[contains(text(), "Weiter")]',
            '//button[contains(text(), "OK")]',
            '//a[contains(text(), "OK")]',
        ]
        clicked_any = False
        for _ in range(3): # Maximal 3 Versuche, um mehrere Dialoge zu schließen
            found_and_clicked = False
            for xpath in generic_buttons:
                try:
                    # Verwende sicher_warten mit kurzer Timeout und prüfem ob klickbar ist
                    button_elem = self.browser.sicher_warten(xpath, timeout=2, sichtbar=True)
                    if button_elem.is_displayed() and button_elem.is_enabled():
                        self.browser.klicken(xpath, timeout=1) # Sofortiger Klick
                        print(f"✅ Generischen Button geklickt: {xpath}")
                        found_and_clicked = True
                        clicked_any = True
                        time.sleep(1) # Kurze Pause nach Klick
                        break # Nach erfolgreichem Klick, fange von vorne an (neuer Dialog?)
                except Exception:
                    pass # Button nicht da oder nicht klickbar
            if not found_and_clicked:
                break # Keine Buttons gefunden, Dialoge sind wahrscheinlich weg

        if clicked_any:
            print("✅ Konfigurationsdialoge erfolgreich behandelt (oder keine mehr vorhanden).")
            return True
        else:
            print("ℹ️ Keine weiteren Konfigurationsdialoge gefunden.")
            return False

    def ist_sprachauswahl(self):
        """
        Prüft, ob die Sprachauswahl-Seite angezeigt wird,
        indem es nach den spezifischen Sprachauswahl-Elementen sucht.
        """
        try:
            # Prüfen, ob DE oder EN Sprachauswahl-Elemente vorhanden sind
            # Wir warten nur kurz, da wir nicht wollen, dass es bei jeder Seite wartet
            self.browser.sicher_warten('//*[@id="uiLanguage-de"] | //*[@id="uiLanguage-en"]', timeout=3, sichtbar=False)
            print("🌐 Sprachauswahlseite erkannt.")
            return True
        except Exception:
            # print("ℹ️ Keine Sprachauswahlseite erkannt.")
            return False

    def set_language(self, lang_code: str = "en"):
        """
        Setzt die Sprache der FritzBox-Oberfläche.
        lang_code: 'de' für Deutsch, 'en' für Englisch.
        """
        if not self.warte_auf_erreichbarkeit():
            raise Exception("FritzBox nicht erreichbar, Sprache kann nicht gesetzt werden.")

        print(f"🌐 Versuche Sprache auf '{lang_code.upper()}' zu setzen...")
        try:
            self.browser.get_url(self.url)
            # Prüfe, ob Sprachauswahl überhaupt angezeigt wird
            if self.ist_sprachauswahl():
                xpath_lang_button = f'//*[@id="uiLanguage-{lang_code}"]'
                if self.browser.klicken(xpath_lang_button):
                    print(f"✅ Sprache '{lang_code.upper()}' ausgewählt.")
                    if self.browser.klicken('//*[@id="submitLangBtn"]'):
                        print("✅ Sprachauswahl bestätigt.")
                        time.sleep(5) # Warte, bis die Seite neu lädt
                        self.language = lang_code
                        return True
            else:
                print("ℹ️ Sprachauswahlseite nicht aktiv. Sprache kann nicht geändert werden.")
                return False
        except Exception as e:
            print(f"❌ Fehler beim Setzen der Sprache auf '{lang_code.upper()}': {e}")
            return False