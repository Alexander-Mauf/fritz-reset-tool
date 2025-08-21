# workflow_orchestrator.py
from fritzbox_api import FritzBox, FirmwareManager
from browser_utils import setup_browser, Browser
import time
import win32gui
import win32con
import ctypes
import re

class WorkflowOrchestrator:
    """
    Steuert den gesamten Workflow zur Verwaltung einer FritzBox.
    Koordiniert die Schritte, handhabt Retries und Benutzerinteraktion.
    """
    def __init__(self):
        self.browser_driver = None
        self.browser = None
        self.fritzbox = None
        self.firmware_manager = FirmwareManager() # FirmwareManager hier instanziieren

    def ensure_browser(self):
        if self.browser is None or not self.browser_still_alive():
            # alten Browser sauber schließen, falls noch offen
            try:
                if self.browser:
                    self.browser.quit()
            except Exception:
                pass

            self.browser_driver = setup_browser()
            self.browser = Browser(self.browser_driver)

            # FritzBox-Objekt immer neu erstellen
            self.fritzbox = FritzBox(self.browser)

    def browser_still_alive(self):
        try:
            # Ping: kleine Abfrage an den Browser
            self.browser.driver.title
            return True
        except Exception:
            return False

    def _fenster_in_vordergrund_holen(self):
        """Bringt das CMD-Fenster in den Vordergrund."""
        try:
            console_hwnd = ctypes.windll.kernel32.GetConsoleWindow()
            win32gui.ShowWindow(console_hwnd, win32con.SW_SHOWNORMAL)
            win32gui.SetForegroundWindow(console_hwnd)
            print("🪟 CMD-Fenster wurde in den Vordergrund gebracht.")
        except Exception as e:
            print(f"⚠️ Fenster-Fokus fehlgeschlagen")

    def _run_step_with_retry(self, description: str, func, *args, **kwargs) -> bool:
        """
        Führt einen Schritt aus mit automatischen Wiederholungen.
        Speziell beim Login:
          - 1. Fehlschlag → Werkreset
          - 2. Fehlschlag → Benutzer nach neuem Passwort fragen
        """
        print(f"\n➡️ {description}...")

        max_attempts = 2
        attempt = 0
        while attempt < max_attempts:
            try:
                self.ensure_browser()
                result = func(*args, **kwargs)

                if result is False:
                    attempt += 1
                    print(f"⚠️ Funktion '{description}' meldete Fehlschlag (Versuch {attempt}/{max_attempts}).")

                    if description.lower().startswith("login") and attempt == 1:
                        # 1️⃣ Werkreset nach erstem Fehlschlag
                        print("\n❗Login fehlgeschlagen. Starte Werkreset, um Standard-PW zu verwenden...")
                        if not self.fritzbox.reset_via_forgot_password():
                            print("❌ Werkseinstellung fehlgeschlagen, Abbruch.")
                            return False
                        print("✅ Werkseinstellung abgeschlossen, versuche erneut Login...")
                        continue

                    elif attempt >= max_attempts:
                        # 2️⃣ Nach erneutem Fehlschlag Benutzer nach neuem Passwort fragen
                        print("\n⚠️ Login erneut fehlgeschlagen. Benutzer muss neues Passwort eingeben...")
                        letztes_passwort = None
                        while True:
                            neues_passwort = input("🔑 Bitte neues Passwort für die FritzBox eingeben: ").strip()
                            if neues_passwort == letztes_passwort:
                                print("⚠️ Passwort identisch zum letzten Versuch, überprüfe Eingabe...")
                            if self.fritzbox.login(neues_passwort):
                                print("✅ Login erfolgreich mit neuem Passwort!")
                                return True
                            else:
                                print("❌ Passwort falsch, bitte erneut eingeben.")
                                letztes_passwort = neues_passwort

                else:
                    print("✅ Schritt erfolgreich.")
                    return True

            except Exception as e:
                attempt += 1
                print(f"⚠️ Fehler bei '{description}' (Versuch {attempt}/{max_attempts}) Error: {e}")
                time.sleep(2)

        # Wenn andere Schritte fehlschlagen, Benutzer entscheiden lassen
        while True:
            auswahl = input("🔁 (W)iederholen, (Ü)berspringen, (B)eenden, (N)eue FritzBox? ").strip().lower()
            if auswahl == "b":
                print("⛔ Vorgang abgebrochen.")
                return False
            elif auswahl == "w":
                return self._run_step_with_retry(description, func, *args, **kwargs)
            elif auswahl == "ü":
                print("⏭️ Schritt übersprungen.")
                return True
            elif auswahl == "n":
                raise RuntimeError("RESTART_NEW_BOX")
            else:
                print("❓ Ungültige Eingabe. Bitte wähle w/ü/b/n.")

    def run_full_workflow(self, password: str) -> str | None:
        """Führt den gesamten FritzBox-Verwaltungs-Workflow anhand einer flexiblen Schritt-Liste aus."""
        self.ensure_browser()

        try:
            workflow_steps = [
                ("FritzBox Erreichbarkeit prüfen", self.fritzbox.warte_auf_erreichbarkeit),
                ("Login durchführen", self.fritzbox.login, password),
                ("Box-Modell ermitteln", self.fritzbox.get_box_model),
                ("Firmware-Version ermitteln", self.fritzbox.get_firmware_version),
                ("Erweiterte Ansicht prüfen/aktivieren", self.fritzbox.activate_expert_mode_if_needed),
                ("Firmware Update Routine", self.fritzbox.update_firmware),
                ("WLAN-Antennen prüfen", self.fritzbox.check_wlan_antennas),
                ("Werkseinstellungen über UI", self.fritzbox.perform_factory_reset_from_ui),
                ("WLAN-Scan Zusammenfassung", self.fritzbox.show_wlan_summary),
            ]

            for step_name, func, *args in workflow_steps:
                try:
                    if not self._run_step_with_retry(step_name, func, *args):
                        return None
                    self._fenster_in_vordergrund_holen()
                except RuntimeError as e:
                    if str(e) == "RESTART_NEW_BOX":
                        return "restart"
                    else:
                        raise
                except Exception:
                    raise Exception


            print("\n🎉 Workflow für diese FritzBox erfolgreich abgeschlossen!")
            auswahl = input("\n(B)eenden oder (N)eue FritzBox bearbeiten? ").strip().lower()
            return None if auswahl == 'b' else "restart"

        except Exception as e:
            print(f"\n❌ Schwerwiegender Fehler im Workflow: {e}")
            time.sleep(10)
            raise Exception

        finally:
            if self.browser:
                self.browser.quit()