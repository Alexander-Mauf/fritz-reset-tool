# fritzbox_api.py
import time
import requests
import os
from pathlib import Path
import tkinter as tk
from tkinter import filedialog
import re
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from browser_utils import Browser


FRITZ_DEFAULT_URL = "http://fritz.box"

class FirmwareManager:
    """Verwaltet Firmware-Dateien und deren Pfade basierend auf dem FritzBox-Modell."""

    def __init__(self):
        self.firmware_mapping = {
            "7590": "8.03",
            "7530": "8.02",
            "6890_LTE": "7.57",
        }

    def _select_firmware_path_manually(self):
        """Öffnet einen Dateidialog zur manuellen Auswahl des Firmware-Pfades."""
        root = tk.Tk()
        root.withdraw()
        file_path = filedialog.askopenfilename(
            title="Firmware-Datei auswählen",
            filetypes=[("Firmware Image", "*.image")]
        )
        root.destroy()
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

        current_dir = Path(__file__).parent
        firmware_filename = f"FRITZ.Box_{box_model}-{target_version}.image"
        firmware_path_auto = current_dir / "firmware und recovery" / firmware_filename

        print(f"ℹ️ Versuche automatischen Firmware-Pfad für {box_model} (Ziel: {target_version}): {firmware_path_auto}")

        if firmware_path_auto.is_file():
            print(f"✅ Firmware-Datei gefunden: {firmware_path_auto}")
            return str(firmware_path_auto)
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
        Führt den Login in die FritzBox durch.
        Versucht, vorhandenen Login zu erkennen und alle auftretenden Dialoge zu behandeln,
        bis das Hauptmenü zugänglich ist.
        Gibt True bei Erfolg, False bei Fehlschlag zurück.
        """
        if not self.warte_auf_erreichbarkeit():
            print("❌ FritzBox nicht erreichbar für Login.")
            return False

        self.password = password

        print("🔐 Login wird versucht...")

        if not force_reload and self.is_logged_in_and_menu_ready(timeout=5):
            print("✅ Bereits eingeloggt und Hauptmenü bereit.")
            return True

        self.browser.get_url(self.url)

        if self._handle_language_selection():
            self.browser.get_url(self.url)

        if not self._check_if_login_required():
            print("❌ Login-Feld nicht gefunden. Unerwarteter Seiten-Zustand vor Login-Versuch.")
            self.is_logged_in = False
            return False

        try:
            if not self.browser.schreiben('//*[@id="uiPass"]', password):
                raise Exception("Passwort konnte nicht in Feld geschrieben werden.")
            if not self.browser.klicken('//*[@id="submitLoginBtn"]'):
                raise Exception("Login-Button konnte nicht geklickt werden.")

            time.sleep(2)

            max_dialog_attempts = 10
            for attempt in range(max_dialog_attempts):
                if self.is_logged_in_and_menu_ready(timeout=5):
                    print(f"✅ Login erfolgreich nach {attempt} Dialogrunden und Hauptmenü zugänglich.")
                    return True

                print(f"Versuche Post-Login-Dialoge zu behandeln (Runde {attempt + 1})...")
                if not self._handle_post_login_dialogs_round():
                    print("❌ Kritischer Fehler während Post-Login-Dialogbehandlung.")
                    self.is_logged_in = False
                    return False

                time.sleep(1)

            print("❌ Maximale Dialogrunden erreicht, Hauptmenü nicht zugänglich.")
            self.is_logged_in = False
            return False

        except Exception as e:
            print(f"❌ Login fehlgeschlagen: {e}")
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

    def neue_firmware_dialog(self) -> bool:
        """Behandelt den Dialog, der nach einer Firmware-Installation erscheinen kann."""
        print("Prüfe ob 'Neue Firmware installiert'-Dialog erscheint...")
        ok_buttons_xpaths = [
            '//button[contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "ok")]',
            '//a[contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "ok")]',
            '//input[contains(translate(@value, "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "ok")]',
            '//*[contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "ok")]',
            '//*[contains(translate(., "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "ok")]',
        ]
        weiter_buttons_xpaths = [
            '//button[contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "weiter")]',
            '//a[contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "weiter")]',
            '//input[contains(translate(@value, "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "weiter")]',
            '//*[contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "weiter")]',
            '//*[contains(translate(., "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "weiter")]',
        ]

        for xpath in ok_buttons_xpaths:
            if self.browser.klicken(xpath, timeout=2):
                print("✅ 'OK' Button im Firmware-Dialog geklickt.")
                time.sleep(1)
                return True
        for xpath in weiter_buttons_xpaths:
            if self.browser.klicken(xpath, timeout=2):
                print("✅ 'Weiter' Button im Firmware-Dialog geklickt.")
                time.sleep(1)
                return True

        print("ℹ️ Kein 'Neue Firmware installiert'-Dialog gefunden oder konnte nicht geklickt werden.")
        return False # Gebe False zurück, um anzuzeigen, dass kein Dialog erfolgreich behandelt wurde

    def dsl_setup_init(self) -> bool:
        """Behandelt initialen DSL-Setup-Dialog (z.B. nach einem Reset)."""
        print("⚙️ Prüfe auf und setze default DSL-Settings (falls vorhanden)...")
        forward_buttons_xpaths = [
            '//*[@id="uiForward"]',
            '//button[contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "weiter")]',
            '//a[contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "weiter")]',
            '//input[contains(translate(@value, "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "weiter")]',
            '//*[contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "weiter")]',
            '//*[contains(translate(., "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "weiter")]',
        ]

        found_and_clicked = False
        for _ in range(3):
            for xpath in forward_buttons_xpaths:
                if self.browser.klicken(xpath, timeout=2):
                    print(f"✅ '{xpath}' im DSL-Setup initial gefunden und geklickt.")
                    found_and_clicked = True
                    time.sleep(1)
                    break
            if not found_and_clicked:
                break

        if found_and_clicked:
            return True
        else:
            print("ℹ️ Kein initialer DSL-Setup-Dialog ('uiForward' oder 'Weiter') gefunden.")
            return False

    def checkbox_fehlerdaten_dialog(self) -> bool:
        """Behandelt den Fehlerdaten-Senden-Dialog."""
        print("🛑 Fehlerdaten-Checkbox prüfen...")
        try:
            checkbox = self.browser.sicher_warten('//*[@id="uiTr069diag"]', timeout=2)
            if checkbox.is_selected():
                checkbox.click()
                print("☑️ Deaktiviert.")
            else:
                print("☑️ Bereits deaktiviert.")

            apply_buttons_xpaths = [
                '//*[@id="uiApply"]',
                '//button[contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "übernehmen")]',
                '//a[contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "übernehmen")]',
                '//input[contains(translate(@value, "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "übernehmen")]',
                '//*[contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "übernehmen")]',
                '//*[contains(translate(., "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "übernehmen")]',
            ]
            for xpath in apply_buttons_xpaths:
                if self.browser.klicken(xpath, timeout=2):
                    print("➡️ Änderungen übernommen (Fehlerdaten).")
                    time.sleep(1)
                    return True

            return True # Checkbox war da, aber evtl. kein Button nötig oder schon deaktiviert
        except Exception:
            print("ℹ️ Keine Fehlerdaten-Checkbox oder Übernehmen-Button gefunden/benötigt.")
            return False

    def skip_configuration(self) -> bool:
        """Versucht, generische Konfigurationsdialoge zu überspringen (z.B. "Weiter"-Buttons)."""
        print("📌 Konfigurationsdialoge überspringen (generisch)...")
        generic_buttons_xpaths = [
            '//*[@id="Button1"]',
            '//button[contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "weiter")]',
            '//a[contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "weiter")]',
            '//input[contains(translate(@value, "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "weiter")]',
            '//*[contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "weiter")]',
            '//*[contains(translate(., "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "weiter")]',
            '//button[contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "ok")]',
            '//a[contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "ok")]',
            '//input[contains(translate(@value, "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "ok")]',
            '//*[contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "ok")]',
            '//*[contains(translate(., "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "ok")]',
        ]

        clicked_any_in_this_round = False
        for xpath in generic_buttons_xpaths:
            try:
                button_elem = self.browser.sicher_warten(xpath, timeout=1, sichtbar=True)
                if button_elem.is_displayed() and button_elem.is_enabled():
                    if self.browser.klicken(xpath, timeout=1):
                        print(f"✅ Generischen Button geklickt: {xpath}")
                        clicked_any_in_this_round = True
                        time.sleep(1)
                        break
            except Exception:
                pass

        if clicked_any_in_this_round:
            return True
        else:
            print("ℹ️ Keine generischen Konfigurationsdialoge gefunden in dieser Runde.")
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

    def perform_factory_reset_from_ui(self) -> bool:
        """Setzt die FritzBox über die Benutzeroberfläche auf Werkseinstellungen zurück (nach Login)."""
        if not self.is_logged_in_and_menu_ready():
            print("❌ Nicht eingeloggt oder Menü nicht bereit. Login für UI-Reset erforderlich.")
            return False

        print("🚨 Werkseinstellungen (aus der Oberfläche)...")

        try:
            if not self.browser.klicken('//*[@id="sys"]', timeout=5):
                print("Konnte nicht auf 'System' klicken.")
                return False
            time.sleep(1)
            if not self.browser.klicken('//*[@id="mSave"]', timeout=5):
                print("Konnte nicht auf 'Sicherung' klicken.")
                return False
            time.sleep(1)

            if not self.browser.klicken('//*[@id="default"]', timeout=5):
                print("Konnte nicht auf 'Werkseinstellungen' klicken.")
                return False
            time.sleep(1)

            confirm_button_xpaths = [
                '//*[@id="content"]/div/button',
                '//button[contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "wiederherstellen")]',
                '//a[contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "wiederherstellen")]',
                '//input[contains(translate(@value, "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "wiederherstellen")]',
            ]
            found_confirm_button = False
            for xpath in confirm_button_xpaths:
                if self.browser.klicken(xpath, timeout=5):
                    found_confirm_button = True
                    break
            if not found_confirm_button:
                print("Konnte keinen Bestätigungsbutton für Werkseinstellungen klicken.")
                return False
            time.sleep(3)

        except Exception as e:
            print(f"❌ Fehler im Reset-Ablauf über UI-Menü: {e}")
            return False

        print("⚠️ℹ️⚠️ Bitte jetzt physischen Knopf an der Box drücken (falls erforderlich)...")

        try:
            def finde_und_klicke_ok_button(driver_instance):
                ok_xpaths = [
                    '//*[@id="Button1"]', # AVM standard
                    '//button[contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "ok")]',
                    '//a[contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "ok")]',
                    '//input[contains(translate(@value, "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "ok")]',
                ]
                for xpath in ok_xpaths:
                    try:
                        btn = WebDriverWait(driver_instance, 1).until(
                            EC.presence_of_element_located((By.XPATH, xpath))
                        )
                        if btn.is_displayed() and btn.is_enabled():
                            btn.click()
                            return True
                    except:
                        pass
                return False

            WebDriverWait(self.browser.driver, 180).until(finde_und_klicke_ok_button)
            print("✅ OK-Button geklickt nach physischer Bestätigung.")
            self.is_reset = True
            time.sleep(25)
            if self.ist_sprachauswahl():
                print("✅ Erfolgreich auf Werkseinstellungen zurückgesetzt.")
                return True
            else:
                print("⚠️ Nicht verifiziert – bitte manuell prüfen.")
                return False
        except Exception as e:
            print(f"❌ Fehler bei OK-Klick nach physischer Bestätigung: {e}")
            return False


    def get_firmware_version(self) -> str | None:
        """Ermittelt die aktuelle Firmware-Version der FritzBox."""
        print("ℹ️ Ermittle Firmware-Version...")
        try:
            if not self.is_logged_in_and_menu_ready():
                print("❌ Nicht eingeloggt oder Menü nicht bereit. Login für Versionsprüfung erforderlich.")
                return None

            if not self.browser.klicken('//*[@id="sys"]', timeout=5): return None
            if not self.browser.klicken('//*[@id="mUp"]', timeout=5): return None

            version_elem = self.browser.sicher_warten('//*[@class="fakeTextInput" or contains(@class, "version_text")]', timeout=5)
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

    def get_box_model(self) -> str | None:
        """Versucht, das Fritzbox-Modell zu ermitteln."""
        print("🔍 Ermittle Box-Modell...")
        if not self.is_logged_in_and_menu_ready():
            print("❌ Nicht eingeloggt oder Menü nicht bereit. Login für Modellermittlung erforderlich.")
            return None

        # VERSUCH 1: Modell direkt von der aktuellen Seite auslesen
        current_page_model_xpaths = [
            '//h1[contains(text(), "FRITZ!Box")]',
            '//span[contains(@class, "version_text") and contains(text(), "FRITZ!Box")]',
            '//div[@class="boxInfo"]/span[contains(text(), "FRITZ!Box")]',
            '//*[contains(@class, "deviceTitle")] | //*[contains(@class, "productname")]',
        ]

        for xpath in current_page_model_xpaths:
            try:
                model_elem = self.browser.sicher_warten(xpath, timeout=1, sichtbar=False)
                model_text = model_elem.text.strip()
                if "FRITZ!Box" in model_text:
                    match = re.search(r'FRITZ!Box ([\w-]+ ?\d{4,}(?: ?LTE)?)', model_text)
                    if match:
                        model_number = match.group(1).replace(" ", "_").strip()
                        self.box_model = model_number
                        print(f"✅ Box-Modell: {self.box_model} (von aktueller Seite ausgelesen).")
                        return self.box_model
            except Exception:
                continue

        print("⚠️ Modell konnte nicht direkt ausgelesen werden. Versuche Navigation zur Übersicht.")

        # VERSUCH 2: Navigation zur Übersichtsseite ('mHome')
        try:
            # Klickt direkt auf den 'Übersicht' Menüpunkt
            if self.browser.klicken('//*[@id="mHome"]', timeout=5):
                time.sleep(2) # Warte, bis die Übersichtsseite geladen ist

                # Erneuter Versuch, das Modell von der Übersichtsseite auszulesen
                for xpath in current_page_model_xpaths:
                    try:
                        model_elem = self.browser.sicher_warten(xpath, timeout=2, sichtbar=True)
                        model_text = model_elem.text.strip()
                        if "FRITZ!Box" in model_text:
                            match = re.search(r'FRITZ!Box ([\w-]+ ?\d{4,}(?: ?LTE)?)', model_text)
                            if match:
                                model_number = match.group(1).replace(" ", "_").strip()
                                self.box_model = model_number
                                print(f"✅ Box-Modell: {self.box_model} (nach Navigation zur Übersicht ausgelesen).")
                                return self.box_model
                    except Exception:
                        continue
            else:
                 print("⚠️ Konnte nicht zur Übersichtsseite navigieren.")

        except Exception as e:
            print(f"❌ Fehler bei der Navigation zur Übersicht: {e}")

        print("❌ Box-Modell konnte nicht eindeutig identifiziert werden.")
        self.box_model = "UNKNOWN"
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
        """Prüft die WLAN-Antennen und Signalstärke."""
        print("📡 WLAN-Antennen prüfen...")
        self.is_wifi_checked = False

        if not self.is_logged_in_and_menu_ready():
            print("❌ Nicht eingeloggt oder Menü nicht bereit. Login für WLAN-Check erforderlich.")
            return False

        for versuch in range(1, max_versuche + 1):
            try:
                if not self.browser.klicken('//*[@id="wlan"]', timeout=5):
                    raise Exception("Konnte nicht auf 'WLAN' klicken.")
                time.sleep(1)
                if not self.browser.klicken('//*[@id="chan"]', timeout=5):
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
                print("❌ Auch nach mehreren Versuchen keine Netzwerke gefunden.")
                return False # Fehler nach Max-Versuchen

        if not rows:
            print("Keine WLAN-Netzwerke zur Analyse gefunden.")
            return False

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
                print(f"⚠️ Fehler beim Verarbeiten eines Netzwerks (#{i+1}): {e}")
                # Fährt fort, um andere Netzwerke zu verarbeiten, aber signalisiert, dass ein Fehler auftrat
                # Je nach Strenge könnte man hier einen Counter führen und bei zu vielen Fehlern False zurückgeben.
        self.is_wifi_checked = True
        return True # Angenommen, der Check lief generell durch, auch wenn einzelne Einträge fehlerhaft waren

    def activate_expert_mode_if_needed(self) -> bool:
        """
        Prüft die FRITZ!OS-Version und aktiviert die erweiterte Ansicht, falls nötig (< 07.15).
        """
        print("🔍 Prüfe, ob erweiterte Ansicht aktiviert werden muss...")
        if not self.os_version:
            print("⚠️ OS-Version unbekannt. Prüfung wird übersprungen.")
            return True  # Gehen von Erfolg aus, um den Workflow nicht zu blockieren

        # Extrahiere Versionsnummer (z.B. aus 'FRITZ!OS: 07.29')
        match = re.search(r'(\d{2})\.(\d{2})', self.os_version)
        if not match:
            print(f"⚠️ Versionsformat '{self.os_version}' nicht erkannt. Prüfung wird übersprungen.")
            return True

        major, minor = int(match.group(1)), int(match.group(2))

        # Prüfung nur für Versionen unter 7.15 durchführen
        if major < 7 or (major == 7 and minor < 15):
            print(f"ℹ️ Version {major}.{minor} erkannt. Erweiterte Ansicht wird geprüft/aktiviert.")
            try:
                if not self.browser.klicken('//*[@id="sys"]', timeout=5): return False
                time.sleep(1)
                if not self.browser.klicken('//*[@id="mSys"] | //*[@id="mSysView"]',
                                            timeout=5): return False  # mSys für alte, mSysView für neuere Versionen
                time.sleep(2)

                # Prüfen, ob die Checkbox für die erweiterte Ansicht existiert und nicht ausgewählt ist
                checkbox_xpath = '//input[@id="expert"]'
                try:
                    checkbox = self.browser.sicher_warten(checkbox_xpath, timeout=5)
                    if not checkbox.is_selected():
                        print("🎚️ Erweiterte Ansicht ist nicht aktiv. Aktiviere sie jetzt...")
                        if self.browser.klicken(checkbox_xpath):
                            # Klicke auf 'Übernehmen'
                            if self.browser.klicken('//*[@id="uiApply"]'):
                                print("✅ Erweiterte Ansicht erfolgreich aktiviert.")
                                time.sleep(3)  # Warte auf das Neuladen der Seite
                                return True
                            else:
                                print("❌ 'Übernehmen'-Button für erweiterte Ansicht nicht gefunden.")
                                return False
                        else:
                            print("❌ Checkbox für erweiterte Ansicht konnte nicht geklickt werden.")
                            return False
                    else:
                        print("✅ Erweiterte Ansicht ist bereits aktiv.")
                        return True
                except Exception:
                    print("ℹ️ Checkbox für erweiterte Ansicht nicht gefunden (möglicherweise immer aktiv).")
                    return True  # Gehen von Erfolg aus
            except Exception as e:
                print(f"❌ Fehler beim Aktivieren der erweiterten Ansicht: {e}")
                return False
        else:
            print("✅ Version ist aktuell genug, keine Prüfung der erweiterten Ansicht nötig.")
            return True


def perform_firmware_update(self, firmware_path: str) -> bool:
    """Führt ein Firmware-Update über die Weboberfläche durch (nach Login)."""
    if not self.is_logged_in_and_menu_ready():
        print("❌ Nicht eingeloggt. Login für Firmware-Update erforderlich.")
        return False
    if not firmware_path or not os.path.exists(firmware_path):
        print(f"❌ Firmware-Datei nicht gefunden unter: {firmware_path}")
        return False

    print(f"🆙 Firmware-Update wird mit Datei gestartet: {os.path.basename(firmware_path)}")

    try:
        # Navigation zum Update-Menü
        if not self.browser.klicken('//*[@id="sys"]', timeout=5): return False
        time.sleep(1)
        if not self.browser.klicken('//*[@id="mUp"]', timeout=5): return False
        time.sleep(1)
        if not self.browser.klicken('//*[@id="userUp"] | //a[contains(text(), "FRITZ!OS-Datei")]',
                                    timeout=5): return False
        time.sleep(2)

        # Optional: Checkbox zum Sichern der Einstellungen deaktivieren
        try:
            checkbox = self.browser.sicher_warten('//*[@id="uiExportCheck"]', timeout=3)
            if checkbox.is_selected():
                checkbox.click()
                print("☑️ Checkbox 'Einstellungen sichern' deaktiviert.")
        except Exception:
            print("ℹ️ Checkbox 'Einstellungen sichern' nicht gefunden, wird übersprungen.")

        # Pfad zur Firmware-Datei eintragen und Update starten
        if not self.browser.schreiben('//*[@id="uiFile"]', firmware_path):
            print("❌ Fehler beim Eintragen des Firmware-Pfads.")
            return False

        # Klick auf "Update starten"
        if not self.browser.klicken('//*[@id="uiUpdate"]'):
            print("❌ Fehler beim Klicken auf 'Update starten'.")
            return False

        print("📤 Firmware wird hochgeladen... Die Box startet nun neu.")
        print("⏳ Der Workflow wird nach dem Neustart mit der Überprüfung der Erreichbarkeit fortgesetzt.")
        # Die Methode kehrt sofort zurück. Der Orchestrator muss warten und neu verbinden.
        return True

    except Exception as e:
        print(f"❌ Unerwarteter Fehler während des Firmware-Updates: {e}")
        return False