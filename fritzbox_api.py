# fritzbox_api.py
import time
import requests
import os
from pathlib import Path
import tkinter as tk
from tkinter import filedialog
import re
import sys
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from browser_utils import Browser


FRITZ_DEFAULT_URL = "http://fritz.box"


# fritzbox_api.py

class FirmwareManager:
    """Verwaltet Firmware-Dateien und deren Pfade für mehrstufige Updates."""

    def __init__(self):
        self.firmware_mapping = {
            "7590": {
                "bridge": "07.59",
                "final": "08.03",
                "bridge_file": "FRITZ.Box_7590-07.59.image", # Beispielhafter Dateiname
                "final_file": "FRITZ.Box_7590-08.03.image"
            },
            "7530": {
                # Für dieses Modell gibt es keinen Zwischenschritt, nur ein finales Ziel
                "final": "08.02",
                "final_file": "FRITZ.Box_7530-08.02.image"
            },
            "6890": {
                # Für dieses Modell gibt es keinen Zwischenschritt, nur ein finales Ziel
                "final": "07.57",
                "final_file": "FRITZ.Box_6890_LTE-07.57.image"
            }
            # Weitere Modelle hier hinzufügen
        }

    def _select_firmware_path_manually(self):
        # ... (diese Methode bleibt unverändert)
        root = tk.Tk()
        root.withdraw()
        file_path = filedialog.askopenfilename(
            title="Firmware-Datei auswählen",
            filetypes=[("Firmware Image", "*.image")]
        )
        root.destroy()
        return file_path

    def get_firmware_path(self, box_model: str, version_type: str = "final") -> str | None:
        """
        Sucht den Pfad für einen bestimmten Versionstyp ("bridge" or "final").
        """
        if not box_model or box_model not in self.firmware_mapping:
            print(f"⚠️ Kein Firmware-Eintrag für Modell '{box_model}' bekannt. Manuelle Auswahl.")
            return self._select_firmware_path_manually()

        model_files = self.firmware_mapping[box_model]
        file_key = f"{version_type}_file" # z.B. "bridge_file" oder "final_file"

        if file_key not in model_files:
            print(f"⚠️ Kein '{version_type}'-Update für Modell {box_model} definiert. Manuelle Auswahl.")
            return self._select_firmware_path_manually()

        firmware_filename = model_files[file_key]

        try:
            current_dir = Path(sys.argv[0]).parent
        except Exception:
            current_dir = Path.cwd()

        firmware_path_auto = current_dir / "firmware und recovery" / firmware_filename
        print(f"ℹ️ Suche {version_type}-Firmware für {box_model} unter: {firmware_path_auto}")

        if firmware_path_auto.is_file():
            print(f"✅ Firmware-Datei gefunden: {firmware_path_auto}")
            return str(firmware_path_auto)
        else:
            print(f"❌ Firmware-Datei nicht gefunden. Bitte manuell auswählen.")
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
        self.password = None
        self.box_model = None
        self.is_wifi_checked = False

    def warte_auf_erreichbarkeit(self, versuche=20, delay=5) -> bool:
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
                    pass
                except Exception as e:
                    print(f"Fehler beim Prüfen der URL {url}: {e}")
            time.sleep(delay)

        print("❌ FritzBox nicht erreichbar.")
        return False

    def _check_if_login_required(self) -> bool:
        """Interne Methode: Prüft, ob das Passwortfeld auf der aktuellen Seite vorhanden ist."""
        try:
            return bool(self.browser.sicher_warten('//*[@id="uiPass" or @type="password"]', timeout=1, sichtbar=False))
        except Exception:
            return False

    def _handle_language_selection(self) -> bool:
        """Interne Methode: Behandelt die Sprachauswahl, falls sie erscheint."""
        try:
            # Hier keinen get_url aufruf! wird vor dem aufruf im login gemacht
            # Prüfe, ob Sprachauswahl-Elemente da sind
            if self.browser.sicher_warten('//*[@id="uiLanguage-en"]', timeout=2, sichtbar=False):
                print("🌐 Sprachauswahl erkannt. Setze auf Englisch...")
                if self.browser.klicken('//*[@id="uiLanguage-en"]'):
                    if self.browser.klicken('//*[@id="submitLangBtn"]'):
                        time.sleep(3)
                        self.language = "en"
                        return True
                    print("⚠️ 'Sprache übernehmen'-Button nicht klickbar.")
                print("⚠️ Sprachauswahl-Button nicht klickbar.")
        except Exception:
            print("ℹ️ Keine Sprachauswahl erkannt oder konnte nicht verarbeitet werden.")
        return False

    def is_main_menu_loaded_and_ready(self, timeout=5) -> bool:
        """
        Prüft, ob die Hauptmenüstruktur der FritzBox geladen und interaktiv ist.
        Sucht nach Schlüssel-Menüpunkten wie WLAN, System etc.
        """
        menu_xpaths = [
            '//*[@id="wlan"]',
            '//*[@id="sys"]',
            '//*[@id="internet"]',
            '//*[@id="home"]',
        ]
        # print(f"🔍 Prüfe auf geladenes und klickbares Hauptmenü (Timeout: {timeout}s)...")
        for xpath in menu_xpaths:
            try:
                element = self.browser.sicher_warten(xpath, timeout=timeout/len(menu_xpaths) if menu_xpaths else timeout, sichtbar=True)
                if element and element.is_displayed() and element.is_enabled():
                    # print(f"✅ Hauptmenü-Element '{xpath}' gefunden und bereit.")
                    return True
            except Exception:
                pass
        # print("❌ Hauptmenü nicht gefunden oder nicht bereit.")
        return False

    def is_logged_in_and_menu_ready(self, timeout=5) -> bool:
        """
        Prüft, ob der Browser auf einer FritzBox-Seite ist, auf der man eingeloggt ist
        und das Hauptmenü sichtbar und interaktiv ist.
        Aktualisiert self.is_logged_in.
        """
        # print(f"🔍 Prüfe Login-Status und Menübereitschaft (Timeout: {timeout}s)...")
        if self._check_if_login_required():
            # print("ℹ️ Login-Feld gefunden. Nicht eingeloggt oder ausgeloggt.")
            self.is_logged_in = False
            return False

        if self.is_main_menu_loaded_and_ready(timeout=timeout):
            # print("✅ Eingeloggt und Hauptmenü bereit.")
            self.is_logged_in = True
            return True
        else:
            # print("❌ Weder Login-Feld noch Hauptmenü erkannt. Unerwarteter Zustand.")
            self.is_logged_in = False
            return False

    def login(self, password: str, force_reload=False) -> bool:
        """
        Führt den Login durch und arbeitet alle nachfolgenden Dialoge in einer
        robusten Schleife ab, bis das Hauptmenü erreichbar ist.
        """
        if not self.warte_auf_erreichbarkeit():
            print("❌ FritzBox nicht erreichbar für Login.")
            return False

        self.password = password
        print("🔐 Login wird versucht...")

        if not force_reload and self.is_logged_in_and_menu_ready(timeout=3):
            print("✅ Bereits eingeloggt und Hauptmenü bereit.")
            return True

        self.browser.get_url(self.url)

        if self._handle_language_selection():
            self.browser.get_url(self.url)

        if self._check_if_login_required():
            try:
                self.browser.schreiben('//*[@id="uiPass"]', password)
                self.browser.klicken('//*[@id="submitLoginBtn"]')
            except Exception as e:
                print(f"❌ Fehler bei der initialen Login-Eingabe: {e}")
                return False
        else:
            print("ℹ️ Kein Login-Feld gefunden. Gehe davon aus, dass ein initialer Dialog aktiv ist.")

        # --- FINALE DIALOG-SCHLEIFE (HYBRID-MODELL) ---
        max_dialog_attempts = 15
        print("...starte Abarbeitung aller möglichen Dialoge...")
        dialog_handlers = [
            self.handle_registration_dialog,
            self.neue_firmware_dialog,
            self.dsl_setup_init,
            self.checkbox_fehlerdaten_dialog,
            self.skip_configuration
        ]

        for attempt in range(max_dialog_attempts):
            print(f"   (Dialog-Runde {attempt + 1}/{max_dialog_attempts})")

            if self.is_logged_in_and_menu_ready(timeout=2):
                print("✅ Login erfolgreich und Hauptmenü zugänglich.")
                self.is_logged_in = True
                return True

            if self._check_if_login_required():
                print("❌ Zurück auf der Login-Seite. Der Login ist fehlgeschlagen.")
                self.is_logged_in = False
                return False

            # Versuche, einen der spezifischen Dialoge zu behandeln
            action_taken = False
            for handler in dialog_handlers:
                if handler():
                    action_taken = True
                    break

            # KORREKTUR: Wenn kein spezifischer Handler zugetroffen hat,
            # wird jetzt die robuste Fallback-Methode aufgerufen.
            if not action_taken:
                print("   ...kein spezifischer Dialog gefunden, versuche generischen Fallback.")
                # Ruft jetzt die korrekte und robuste Methode auf.
                self._handle_any_dialog_button()

            time.sleep(1.5) # Pause zwischen den Runden

        print("❌ Login-Vorgang abgebrochen: Nach mehreren Versuchen konnte das Hauptmenü nicht erreicht werden.")
        self.is_logged_in = False
        return False

    def _handle_post_login_dialogs_round(self) -> bool:
        """
        Versucht eine Runde aller bekannten Post-Login-Dialoge zu behandeln.
        Gibt True zurück, wenn die Runde ohne kritischen Fehler abgeschlossen wurde.
        Gibt False zurück, wenn ein kritischer Fehler (z.B. Logout) erkannt wurde.
        """
        print("⚙️ Starte Runde zur Behandlung von Post-Login-Dialogen...")
        dialog_handlers = [
            self.neue_firmware_dialog,
            self.dsl_setup_init,
            self.checkbox_fehlerdaten_dialog,
            self.skip_configuration,
        ]

        found_and_handled_any_dialog_in_this_round = False

        for handler in dialog_handlers:
            try:
                if not self.is_logged_in_and_menu_ready(timeout=2):
                    print(f"❌ Logout oder unerwarteter Zustand vor Aufruf von '{handler.__name__}'.")
                    return False

                handler_result = handler()
                if handler_result:
                    found_and_handled_any_dialog_in_this_round = True
                    time.sleep(1)

            except Exception as e:
                print(f"❌ Schwerwiegender Fehler beim Behandeln von Dialog '{handler.__name__}': {e}")
                return False

        if not found_and_handled_any_dialog_in_this_round:
            print("ℹ️ Keine weiteren bekannten Dialoge in dieser Runde gefunden.")
        else:
            print("✅ Einige Dialoge in dieser Runde behandelt.")

        return True

    def _handle_any_dialog_button(self) -> bool:
        """
        Sucht nach einer Liste von generischen "positiven" Buttons (OK, Weiter, etc.)
        und klickt den ersten, den er findet. Gibt True zurück, wenn ein Klick erfolgte.
        """
        # Priorisierte Liste von Buttons. Spezifische IDs und Namen zuerst.
        positive_buttons_xpaths = [
            '//*[@id="uiApply"]',
            '//button[@name="apply"]',  # <--- NEU basierend auf deinem Feedback
            '//*[@id="uiForward"]',
            '//button[contains(translate(text(), "WEITER", "weiter"), "weiter")]',
            '//a[contains(translate(text(), "WEITER", "weiter"), "weiter")]',
            '//button[contains(translate(text(), "OK", "ok"), "ok")]',
            '//a[contains(translate(text(), "OK", "ok"), "ok")]',
            '//button[contains(translate(text(), "ÜBERNEHMEN", "übernehmen"), "übernehmen")]',
            '//button[contains(translate(text(), "FERTIGSTELLEN", "fertigstellen"), "fertigstellen")]',
            '//*[@id="submit_button"]',
            '//*[@id="Button1"]'
        ]

        for xpath in positive_buttons_xpaths:
            # Wir nutzen einen sehr kurzen Timeout, da wir nur prüfen, ob der Button gerade da ist.
            if self.browser.klicken(xpath, timeout=0.5, versuche=1):
                print(f"✅ Generischen Dialog-Button geklickt: {xpath}")
                return True
        return False

    def neue_firmware_dialog(self) -> bool:
        """Behandelt den Dialog 'Neue Firmware wurde installiert'."""
        try:
            # Suchen nach einem eindeutigen Text oder Button dieses Dialogs
            if self.browser.sicher_warten('//h1[contains(text(), "FRITZ!OS wurde aktualisiert")]', timeout=1, sichtbar=False):
                print("...behandle 'Firmware aktualisiert'-Dialog.")
                # Klickt auf OK oder Weiter
                self.browser.klicken('//button[contains(text(), "OK")] | //a[contains(text(), "Weiter")]', timeout=3, versuche=1)
                return True
        except Exception:
            pass # Element nicht gefunden, also war dieser Dialog nicht da.
        return False

    def dsl_setup_init(self) -> bool:
        """Behandelt den initialen DSL-Einrichtungs-Assistenten."""
        try:
             # Dieser Assistent wird oft durch den "Weiter"-Button mit der ID 'uiForward' eingeleitet
            if self.browser.sicher_warten('//*[@id="uiForward"]', timeout=1, sichtbar=False):
                print("...behandle initialen DSL-Setup-Dialog.")
                self.browser.klicken('//*[@id="uiForward"]', timeout=3, versuche=1)
                return True
        except Exception:
            pass
        return False

    def checkbox_fehlerdaten_dialog(self) -> bool:
        """Behandelt den Dialog zum Senden von Fehlerdiagnosedaten."""
        try:
            checkbox = self.browser.sicher_warten('//*[@id="uiTr069diag"]', timeout=1)
            print("...behandle Fehlerdaten-Dialog.")
            if checkbox.is_selected():
                checkbox.click()
            # Klickt danach auf "Übernehmen"
            self.browser.klicken('//*[@id="uiApply"]')
            return True
        except Exception:
            pass
        return False

    def _close_any_overlay(self) -> bool:
        """
        Sucht nach einem generischen "Schließen"-Button und klickt ihn, falls vorhanden.
        Diese Version ist "crash-sicher" und verursacht keinen Fehler, wenn nichts gefunden wird.
        """
        try:
            # Wir verwenden find_elements (plural), was eine leere Liste zurückgibt statt einen Fehler zu werfen.
            close_buttons = self.browser.driver.find_elements(By.XPATH,
                                                              '//button[.//div[text()="Schließen"] or text()="Schließen"]')

            # Nur wenn die Liste nicht leer ist, also ein Button gefunden wurde:
            if close_buttons:
                print("...generisches Overlay gefunden, versuche es zu schließen.")
                # Klicke den ersten gefundenen Button mit einem sicheren JS-Klick
                self.browser.driver.execute_script("arguments[0].click();", close_buttons[0])
                print("✅ Generisches Overlay geschlossen.")
                time.sleep(1)
                return True
        except Exception as e:
            # Fängt alle anderen möglichen Fehler ab, um Abstürze zu vermeiden.
            print(f"⚠️ Kleiner Fehler beim Versuch, ein Overlay zu schließen (wird ignoriert): {e}")
            pass
        return False

    def handle_registration_dialog(self) -> bool:
        """Behandelt den "Informiert bleiben"-Dialog."""
        try:
            # Eindeutiger Text dieses Dialogs
            if self.browser.sicher_warten('//h1[contains(text(), "Informiert bleiben")]', timeout=1, sichtbar=False):
                print("...behandle 'Informiert bleiben'-Dialog.")
                # Klickt auf OK
                self.browser.klicken('//*[@id="content"]/div[2]/button[1]', timeout=3, versuche=1)
                return True
        except Exception:
            pass  # Dialog war nicht da.
        return False

    def skip_configuration(self) -> bool:
        """Behandelt generische Konfigurations-Dialoge mit einem "Schließen" oder "OK" Button."""
        try:
             # Dieser Dialog hat oft einen allgemeinen Button mit ID "Button1"
            if self.browser.sicher_warten('//*[@id="Button1"]', timeout=1, sichtbar=False):
                print("...überspringe generischen Konfigurations-Dialog.")
                self.browser.klicken('//*[@id="Button1"]', timeout=3, versuche=1)
                return True
        except Exception:
            pass
        return False

    def reset_via_forgot_password(self) -> bool:
        """Leitet den Werksreset über den 'Passwort vergessen'-Link ein (ohne Login)."""
        if not self.warte_auf_erreichbarkeit():
            print("❌ FritzBox nicht erreichbar für Reset.")
            return False
        print("🚨 Werkseinstellungen einleiten (via 'Passwort vergessen')...")
        self.browser.get_url(self.url)

        kandidaten_xpaths = [
            '//*[@id="dialogFoot"]/a',
            '//a[contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "passwort vergessen")]',
            '//button[contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "passwort vergessen")]',
            '//*[contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "passwort vergessen")]',
        ]

        found_reset_link = False
        for xpath in kandidaten_xpaths:
            if self.browser.klicken(xpath, timeout=5):
                print(f"🔁 Reset-Link gefunden und geklickt ({xpath})")
                found_reset_link = True
                break
        if not found_reset_link:
            print("❌ Kein Reset-Link gefunden.")
            return False

        if self.browser.klicken('//*[@id="sendFacReset"]', timeout=5):
            print("🔁 Reset ausgelöst, warte auf Neustart...")
            time.sleep(60)
            self.is_reset = True
            if self.ist_sprachauswahl():
                print("✅ FritzBox erfolgreich auf Werkseinstellungen zurückgesetzt und Sprachauswahl erreicht.")
                return True
            else:
                print("⚠️ Reset ausgelöst, aber Sprachauswahl nicht verifiziert. Bitte manuell prüfen.")
                return False
        else:
            print("❌ Fehler beim Bestätigen des Resets via 'sendFacReset'.")
            return False

    def activate_expert_mode_if_needed(self) -> bool:
        """
        Prüft, ob der "FRITZ!OS-Datei"-Reiter klickbar ist. Wenn nicht, wird die
        erweiterte Ansicht aktiviert. Dies ist die zuverlässigste Methode.
        """
        print("🔍 Prüfe, ob erweiterte Ansicht aktiv ist (via Update-Reiter-Status)...")
        if not self.os_version: return True

        # Extrahiert die Versionsnummer, um zu entscheiden, ob die Prüfung nötig ist
        match = re.search(r'(\d{1,2})\.(\d{2})', self.os_version)
        if not match: return True
        major, minor = int(match.group(1)), int(match.group(2))

        # Bei alten Versionen ist die erweiterte Ansicht oft nicht standardmäßig aktiv
        if major < 7 or (major == 7 and minor < 15):
            try:
                print("...navigiere zur Update-Seite, um den Status zu prüfen.")
                # VERSUCH 1: Klicke direkt auf "Update", falls Menü schon offen ist
                if not self.browser.klicken('//*[@id="mUp"]', timeout=2, versuche=1):
                    # VERSUCH 2: Wenn das fehlschlägt, klicke erst auf "System" und dann auf "Update"
                    print("...'Update'-Menü nicht direkt sichtbar, öffne 'System'-Menü.")
                    if not self.browser.klicken('//*[@id="sys"]', timeout=5): return False
                    time.sleep(1)
                    if not self.browser.klicken('//*[@id="mUp"]', timeout=5): return False

                time.sleep(2)  # Warten, bis die Seite und ihre Elemente geladen sind

                # Prüfe den Zustand des "FRITZ!OS-Datei"-Reiters
                try:
                    update_tab = self.browser.sicher_warten('//*[@id="userUp"]', timeout=5)
                    print("✅ Erweiterte Ansicht ist bereits aktiv.")
                except:
                    print("...'FRITZ!OS-Datei' ist deaktiviert. Aktiviere erweiterte Ansicht.")
                    # Menü (Burger-Icon) öffnen
                    menu_icon = self.browser.sicher_warten('//*[@id="blueBarUserMenuIcon"]', timeout=5)
                    self.browser.driver.execute_script("arguments[0].click();", menu_icon)
                    WebDriverWait(self.browser.driver, 5).until(
                        EC.presence_of_element_located(
                            (By.XPATH, '//*[@id="blueBarUserMenuIcon" and @aria-expanded="true"]'))
                    )
                    # Link für erweiterte Ansicht klicken
                    expert_link = self.browser.sicher_warten('//a[@id="expert"]', timeout=5)
                    self.browser.driver.execute_script("arguments[0].click();", expert_link)
                    print("✅ 'Erweiterte Ansicht' erfolgreich umgeschaltet.")
                    time.sleep(3)

                # Zurück zur Hauptseite für einen sauberen Zustand
                self.browser.klicken('//*[@id="mHome"] | //*[@id="overview"]')
                return True

            except Exception as e:
                print(f"❌ Fehler beim Prüfen/Umschalten der erweiterten Ansicht: {e}")
                return False
        else:
            print("✅ Version ist aktuell genug, keine Prüfung der erweiterten Ansicht nötig.")
            return True

    def perform_factory_reset_from_ui(self) -> bool:
        """
        Setzt die FritzBox auf Werkseinstellungen zurück und stellt vorher
        einen sauberen UI-Zustand sicher.
        """
        if not self.is_logged_in_and_menu_ready():
            print("❌ Nicht eingeloggt. Login für UI-Reset erforderlich.")
            return False

        print("🚨 Werkseinstellungen (aus der Oberfläche)...")

        try:
            # UI-Zustand stabilisieren
            print("...navigiere zur Hauptseite für einen sauberen Start.")
            self._close_any_overlay()
            self.browser.klicken('//*[@id="mHome"] | //*[@id="overview"]')
            time.sleep(1)

            # VERSUCH 1: Klicke direkt auf "Sicherung", falls Menü schon offen
            if not self.browser.klicken('//*[@id="mSave"] | //a[contains(@href, "backup.lua")]', timeout=2, versuche=1):
                # VERSUCH 2: Wenn das fehlschlägt, klicke erst auf "System"
                print("...'Sicherung' nicht direkt sichtbar, öffne 'System'-Menü.")
                if not self.browser.klicken('//*[@id="sys"]', timeout=5):
                    print("Konnte nicht auf 'System' klicken.")
                    return False
                time.sleep(1)
                # Und dann auf "Sicherung"
                if not self.browser.klicken('//*[@id="mSave"] | //a[contains(@href, "backup.lua")]', timeout=5):
                    print("Konnte den Menüpunkt 'Sicherung' nicht finden.")
                    return False

            time.sleep(1)

            # Navigation zum Tab "Werkseinstellungen"
            if not self.browser.klicken('//*[@id="default"] | //a[contains(text(), "Werkseinstellungen")]', timeout=5):
                print("Konnte nicht auf den Tab 'Werkseinstellungen' klicken.")
                return False
            time.sleep(1)

            # Klick auf den finalen Bestätigungsbutton
            confirm_button_xpaths = [
                '//*[@id="uiDefaults"]',
                '//*[@id="content"]/div/button',
                '//button[contains(text(), "Werkseinstellungen laden")]'
            ]
            found_confirm_button = False
            for xpath in confirm_button_xpaths:
                if self.browser.klicken(xpath, timeout=2, versuche=1):
                    print(f"✅ Bestätigungs-Button geklickt ({xpath}).")
                    found_confirm_button = True
                    break

            if not found_confirm_button:
                print("Konnte keinen Bestätigungsbutton für die Werkseinstellungen finden.")
                return False

            time.sleep(3)

        except Exception as e:
            print(f"❌ Fehler im Reset-Ablauf über UI-Menü: {e}")
            return False

        # bestätigen, dass der WES reset ausgeführt werden soll
        ok_button_xpath = '//*[@id="Button1"] | //button[text()="OK"]'
        btn = self.browser.sicher_warten(ok_button_xpath, timeout=180, sichtbar=True)
        btn.click()

        print("⚠️ℹ️⚠️ Bitte jetzt physischen Knopf an der Box drücken (falls erforderlich)...")
        try:
            ok_button_xpath = '//*[@id="Button1"] | //button[text()="OK"]'
            btn = self.browser.sicher_warten(ok_button_xpath, timeout=180, sichtbar=True)
            btn.click()
            print("✅ OK-Button geklickt nach physischer Bestätigung.")
            self.is_reset = True
            time.sleep(25)  # Zeit für den Neustart geben
            self.warte_auf_erreichbarkeit()
            if self.ist_sprachauswahl():
                print("✅ Erfolgreich auf Werkseinstellungen zurückgesetzt.")
                return True
            else:
                print("⚠️ Reset abgeschlossen, aber Sprachauswahl nicht verifiziert.")
                return True
        except Exception as e:
            print(f"❌ Fehler beim Warten auf den finalen OK-Klick: {e}")
            return False

    def get_firmware_version(self) -> str | bool:
        """Ermittelt die aktuelle Firmware-Version der FritzBox."""
        print("ℹ️ Ermittle Firmware-Version...")
        try:
            if not self.is_logged_in_and_menu_ready():
                print("❌ Nicht eingeloggt oder Menü nicht bereit. Login für Versionsprüfung erforderlich.")
                return False

            # Zur Sicherheit zur Hauptseite, dann ins Menü
            self.browser.klicken('//*[@id="mHome"] | //*[@id="overview"]')
            time.sleep(1)
            if not self.browser.klicken('//*[@id="sys"]', timeout=5): return False
            if not self.browser.klicken('//*[@id="mUp"]', timeout=5): return False

            version_elem = self.browser.sicher_warten('//*[@class="fakeTextInput" or contains(@class, "version_text")]',
                                                      timeout=5)
            version_text = version_elem.text.strip()

            if version_text:
                self.os_version = version_text
                print(f"✅ Firmware-Version: {self.os_version}")
                return self.os_version
            else:
                print("❌ Keine Firmware-Version gefunden auf der Update-Seite.")
                return False  # KORREKTUR: Bei Fehler False zurückgeben
        except Exception as e:
            print(f"❌ Fehler beim Ermitteln der Firmware-Version: {e}")
            return False  # KORREKTUR: Bei Fehler False zurückgeben

        # fritzbox_api.py

    def get_box_model(self) -> str | bool:
        """
        Ermittelt das Fritzbox-Modell mit einer robusten 3-Stufen-Strategie.
        Gibt bei Fehlschlag False zurück, um den Workflow korrekt zu steuern.
        """
        print("🔍 Ermittle Box-Modell (robuste Methode)...")
        self._close_any_overlay()

        if not self.is_logged_in_and_menu_ready():
            print("❌ Nicht eingeloggt. Login für Modellermittlung erforderlich.")
            return False

        # --- Stufe 1: Suche auf der aktuellen Seite ---
        print("   (Stufe 1/3: Suche auf aktueller Seite)")
        xpaths_to_check = [
            '//*[@id="blueBarTitel"]',
            '//span[contains(@class, "version_text")]',
            '//div[@class="boxInfo"]/span'
        ]
        for xpath in xpaths_to_check:
            try:
                element = self.browser.sicher_warten(xpath, timeout=1, sichtbar=False)
                model = self._extract_model_number(element)
                if model:
                    self.box_model = model
                    print(f"✅ Box-Modell: {self.box_model} (gefunden auf aktueller Seite).")
                    return self.box_model
            except Exception:
                continue

        # --- Stufe 2: Navigation zur Übersichtsseite ---
        print("   (Stufe 2/3: Suche auf Übersichtsseite)")
        if self.browser.klicken('//*[@id="overview"] | //*[@id="mHome"]', timeout=3):
            time.sleep(2)
            for xpath in xpaths_to_check:
                try:
                    element = self.browser.sicher_warten(xpath, timeout=1, sichtbar=False)
                    model = self._extract_model_number(element)
                    if model:
                        self.box_model = model
                        print(f"✅ Box-Modell: {self.box_model} (gefunden auf Übersichtsseite).")
                        return self.box_model
                except Exception:
                    continue

        print("❌ Box-Modell konnte nicht identifiziert werden.")
        self.box_model = "UNKNOWN"
        return False  # KORREKTUR: Bei Fehlschlag False zurückgeben, nicht None.

    def _extract_model_number(self, element) -> str | None:
        """
        Extrahiert die 4-stellige Modellnummer aus dem textContent eines Elements.
        Diese Methode ist zuverlässiger als .text für unsichtbare Elemente.
        """
        try:
            # .get_attribute("textContent") liest Text auch aus versteckten Elementen
            text_content = element.get_attribute("textContent").strip()

            # Dieser Regex sucht einfach nach der ersten 4-stelligen Zahl.
            match = re.search(r'(\d{4,})', text_content)
            if match:
                model_number = match.group(1)
                # Fall für LTE-Modelle
                if "LTE" in text_content:
                    return f"{model_number}_LTE"
                return model_number
        except Exception:
            return None
        return None

    def dsl_setup_wizard(self) -> bool:
        """Durchläuft den DSL-Setup-Wizard (falls er nach einem Reset/Update erscheint)."""
        print("⚙️ Prüfe auf und durchlaufe Setup-Wizard (DSL)...")
        # Hier auch prüfen, ob eingeloggt, falls der Wizard nach einem Login erscheint, aber nicht direkt nach Reset.
        # Wenn der Wizard direkt nach Reset kommt, ist kein Login möglich, daher ist diese Prüfung optional.
        # if not self.is_logged_in_and_menu_ready():
        #    print("❌ Nicht eingeloggt. Wizard kann ggf. nicht behandelt werden.")
        #    return False

        try:
            # Versuche zuerst, den Direktlink zum Überspringen zu finden/klicken
            if self.browser.klicken('//*[@id="dlg_welcome"]/p[3]/a', timeout=5):
                print("✅ Direktlink zum Überspringen des Wizards gefunden und geklickt.")
                time.sleep(2)
                return True
            else:
                print("⚠️ Kein Direktlink zum Überspringen – versuche manuellen Ablauf des Wizards.")
                wizard_xpaths = [
                    '//*[@id="uiForward"]',
                    '//*[@id="uiSkip"]',
                    '//*[@id="uiWizFooterBtns"]/button',
                    '//*[@id="uiFinish"]',
                    '//*[@id="Button1"]'
                ]
                found_and_clicked_any = False
                for xpath in wizard_xpaths:
                    try:
                        if self.browser.klicken(xpath, timeout=3):
                            print(f"➡️ Wizard-Schritt mit {xpath} geklickt.")
                            found_and_clicked_any = True
                            time.sleep(2)
                    except Exception:
                        pass # Element nicht gefunden oder Klick fehlgeschlagen, Wizard ist wohl durch

                if found_and_clicked_any:
                    return True
                else:
                    print("ℹ️ DSL-Wizard-Schritte nicht gefunden oder bereits abgeschlossen.")
                    return False

        except Exception as e:
            print(f"❌ Schwerwiegender Fehler im DSL-Setup-Wizard: {e}")
            return False

    def ist_sprachauswahl(self) -> bool:
        """
        Prüft, ob die Sprachauswahl-Seite angezeigt wird,
        indem es nach den spezifischen Sprachauswahl-Elementen sucht.
        """
        try:
            self.browser.sicher_warten('//*[@id="uiLanguage-de"] | //*[@id="uiLanguage-en"]', timeout=3, sichtbar=False)
            print("🌐 Sprachauswahlseite erkannt.")
            return True
        except Exception:
            # print("ℹ️ Keine Sprachauswahlseite erkannt.")
            return False

    def set_language(self, lang_code: str = "en") -> bool:
        """
        Setzt die Sprache der FritzBox-Oberfläche.
        lang_code: 'de' für Deutsch, 'en' für Englisch.
        """
        if not self.warte_auf_erreichbarkeit():
            print("❌ FritzBox nicht erreichbar, Sprache kann nicht gesetzt werden.")
            return False

        print(f"🌐 Versuche Sprache auf '{lang_code.upper()}' zu setzen...")
        try:
            self.browser.get_url(self.url)
            if self.ist_sprachauswahl():
                xpath_lang_button = f'//*[@id="uiLanguage-{lang_code}"]'
                if self.browser.klicken(xpath_lang_button, timeout=5):
                    print(f"✅ Sprache '{lang_code.upper()}' ausgewählt.")
                    if self.browser.klicken('//*[@id="submitLangBtn"]', timeout=5):
                        print("✅ Sprachauswahl bestätigt.")
                        time.sleep(5)
                        self.language = lang_code
                        return True
                    print("❌ Sprachauswahl-Bestätigungsbutton nicht gefunden.")
                    return False
                print(f"❌ Sprachauswahlbutton für '{lang_code.upper()}' nicht gefunden.")
                return False
            else:
                print("ℹ️ Sprachauswahlseite nicht aktiv. Sprache kann nicht geändert werden.")
                return False
        except Exception as e:
            print(f"❌ Fehler beim Setzen der Sprache auf '{lang_code.upper()}': {e}")
            return False

    def check_wlan_antennas(self, max_versuche=2) -> bool:
        """
        Prüft WLAN-Antennen; erkennt automatisch die UI-Version (modern vs. alt)
        und ist gegen StaleElement-Fehler in beiden Fällen abgesichert.
        """
        print("📡 WLAN-Antennen prüfen...")
        self._close_any_overlay()
        if not self.is_logged_in_and_menu_ready():
            return False

        for versuch in range(1, max_versuche + 1):
            try:
                if not self.browser.klicken('//*[@id="wlan"]', timeout=5): raise Exception(
                    "Konnte 'WLAN' nicht klicken.")
                time.sleep(1)
                if not self.browser.klicken('//*[@id="chan"]', timeout=5): raise Exception(
                    "Konnte 'Funkkanal' nicht klicken.")
                time.sleep(5)

                # --- Logik für MODERNE UI (div-basiert) ---
                modern_row_xpath = '//div[@class="flexRow" and .//div[@prefid="rssi"]]'
                num_modern_rows = len(self.browser.driver.find_elements(By.XPATH, modern_row_xpath))

                if num_modern_rows > 0:
                    print(f"📶 Moderne UI erkannt. {num_modern_rows} Netzwerke gefunden.")
                    print("\n📋 Ergebnisübersicht:\n")
                    for i in range(num_modern_rows):
                        try:
                            row = self.browser.driver.find_element(By.XPATH, f"({modern_row_xpath})[{i + 1}]")
                            name = row.find_element(By.XPATH, './/div[@prefid="name"]').text.strip()
                            freq = row.find_element(By.XPATH, './/div[@prefid="band"]').text.strip()
                            channel = row.find_element(By.XPATH, './/div[@prefid="channel"]').text.strip()
                            mac = row.find_element(By.XPATH, './/div[@prefid="mac"]').text.strip()
                            signal_title = row.find_element(By.XPATH, './/div[@prefid="rssi"]').get_attribute(
                                "title").strip()
                            self._print_wlan_entry(i, name, freq, channel, mac, signal_title)
                        except Exception as e:
                            print(f"⚠️ Fehler beim Verarbeiten von Netzwerk #{i + 1}: {e}")
                    self.is_wifi_checked = True
                    return True

                # --- Fallback-Logik für ALTE UI (Tabellen-basiert) ---
                old_table_row_xpath = '//tbody[@id="uiScanResultBody"]/tr'
                num_table_rows = len(self.browser.driver.find_elements(By.XPATH, old_table_row_xpath))

                if num_table_rows > 0:
                    print(f"📶 Alte Tabellen-UI erkannt. {num_table_rows} Netzwerke gefunden.")
                    print("\n📋 Ergebnisübersicht:\n")
                    for i in range(num_table_rows):
                        try:
                            row = self.browser.driver.find_element(By.XPATH, f"({old_table_row_xpath})[{i + 1}]")
                            cols = row.find_elements(By.TAG_NAME, 'td')
                            if len(cols) < 4: continue

                            signal_title = cols[0].get_attribute("title").strip()
                            name = cols[1].text.strip()
                            freq = cols[2].text.strip() # this is apparently freq in the old Version
                            mac = cols[3].text.strip()
                            channel = cols[4].text.strip() # fragwürdig
                            self._print_wlan_entry(i, name, freq, channel, mac, signal_title)
                        except Exception as e:
                            print(f"⚠️ Fehler beim Verarbeiten von Netzwerk #{i + 1}")
                    self.is_wifi_checked = True
                    return True

                # Wenn keine der beiden Suchen erfolgreich war
                print(f"⚠️ Keine WLAN-Netzwerke gefunden (Versuch {versuch}/{max_versuche}).")

            except Exception as e:
                print(f"❌ Fehler beim Zugriff auf WLAN-Liste (Versuch {versuch}): {e}")

            if versuch < max_versuche: time.sleep(5)

        print("❌ Auch nach mehreren Versuchen keine Netzwerke gefunden.")
        return False

    def _print_wlan_entry(self, index, name, freq, channel, mac, signal_title):
        """Hilfsfunktion zur formatierten Ausgabe eines WLAN-Eintrags."""
        try:
            signal_val = signal_title.replace('%', '').replace('<', '')
            signal_strength = int(signal_val or 0)

            if signal_strength <= 30:
                emoji = "📶🔴"
            elif signal_strength <= 60:
                emoji = "📶🟡"
            else:
                emoji = "📶🟢"

            print(f"{index + 1}. {name} | {freq} | Kanal {channel} | MAC: {mac} | Signal: {signal_title} {emoji}")
        except Exception as e:
            print(f"⚠️ Fehler beim Verarbeiten von Netzwerk #{index + 1}: {e}")

    def perform_firmware_update(self, firmware_path: str) -> bool:
        """Führt ein Firmware-Update durch und stellt vorher einen sauberen UI-Zustand her."""
        if not self.is_logged_in_and_menu_ready():
            print("❌ Nicht eingeloggt. Login für Firmware-Update erforderlich.")
            return False
        if not firmware_path or not os.path.exists(firmware_path):
            print(f"❌ Firmware-Datei nicht gefunden unter: {firmware_path}")
            return False

        print(f"🆙 Firmware-Update wird mit Datei gestartet: {os.path.basename(firmware_path)}")

        try:
            # NEU: Zur Sicherheit zur Hauptseite navigieren, um einen definierten Startpunkt zu haben.
            print("...navigiere zur Hauptseite für einen sauberen Start.")
            self.browser.klicken('//*[@id="mHome"] | //*[@id="overview"]')
            time.sleep(1)

            # Schritt 1: Navigation zum Update-Menü
            if not self.browser.klicken('//*[@id="sys"]', timeout=5): return False
            time.sleep(1)
            if not self.browser.klicken('//*[@id="mUp"]', timeout=5): return False
            time.sleep(1)
            if not self.browser.klicken('//*[@id="userUp"] | //a[contains(text(), "FRITZ!OS-Datei")]',
                                        timeout=5): return False
            time.sleep(1)

            # ... (der Rest der Methode bleibt gleich) ...
            print("...warte auf die Seite für das Date-Update.")
            try:
                checkbox = self.browser.sicher_warten('//*[@id="uiExportCheck"]', timeout=10)
            except Exception as e:
                print(f"❌ Die Seite für das Firmware-Update konnte nicht geladen werden (Checkbox nicht gefunden): {e}")
                return False

            if checkbox.is_selected():
                print("...deaktiviere die Checkbox 'Einstellungen sichern'.")
                checkbox.click()
                time.sleep(1)

            print("...warte auf das Datei-Eingabefeld.")
            try:
                file_input = self.browser.sicher_warten('//*[@id="uiFile"]', timeout=10)
            except Exception as e:
                print(f"❌ Das Datei-Eingabefeld ist nicht erschienen: {e}")
                return False

            file_input.send_keys(firmware_path)
            print("✅ Firmware-Pfad erfolgreich eingetragen.")

            if not self.browser.klicken('//*[@id="uiUpdate"]'):
                print("❌ Fehler beim Klicken auf 'Update starten'.")
                return False

            print("📤 Firmware wird hochgeladen... Die Box startet nun neu.")
            # --- NEU: Aktiv auf die Box warten ---
            # Wir geben ihr großzügig Zeit (40 Versuche * 10s = 400s)
            time.sleep(45)
            if self.warte_auf_erreichbarkeit(versuche=40, delay=10):
                print("✅ Box ist nach dem Update wieder erreichbar.")
                return True
            else:
                print("❌ Box ist nach dem Update nicht wieder erreichbar.")
                return False

        except Exception as e:
            print(f"❌ Unerwarteter Fehler während des Firmware-Updates: {e}")
            return False