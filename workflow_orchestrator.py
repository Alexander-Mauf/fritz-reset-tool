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
        Führt einen einzelnen Schritt aus und bietet Optionen zur Wiederholung/Überspringen bei Fehlern.
        Gibt True zurück, wenn der Schritt erfolgreich war oder übersprungen wurde, False bei Abbruch.
        """
        print(f"\n➡️ {description}...")

        max_attempts = 2
        for attempt in range(max_attempts):
            try:
                if self.browser is None or self.browser.driver is None:
                    print("⚠️ Browser-Instanz verloren – starte neu...")
                    from browser_utils import setup_browser, Browser
                    self.browser_driver = setup_browser()
                    self.browser = Browser(self.browser_driver)
                    self.fritzbox.browser = self.browser
                    print("✅ Neuer Browser verbunden.")

                result = func(*args, **kwargs)

                # Eine explizite Rückgabe von False durch die Funktion signalisiert einen kontrollierten Fehlschlag.
                if result is False:
                    print(
                        f"⚠️ Funktion '{description}' meldete expliziten Fehlschlag (Versuch {attempt + 1}/{max_attempts}).")
                    if attempt < max_attempts - 1:
                        print("🔁 Versuche es erneut...")
                        time.sleep(2)
                        continue
                    else:
                        # Nach allen automatischen Versuchen ist der Schritt fehlgeschlagen.
                        # Wir brechen hier aus der Schleife aus, um zur Benutzerabfrage zu gelangen.
                        break

                print("✅ Schritt erfolgreich.")
                return True

            except Exception as e:
                print(f"⚠️ Fehler bei '{description}' (Versuch {attempt + 1}/{max_attempts})")
                if attempt < max_attempts - 1:
                    print("🔁 Versuche es erneut...")
                    time.sleep(2)
                else:
                    # Nach allen automatischen Versuchen ist der Schritt fehlgeschlagen.
                    # Wir brechen hier aus der Schleife aus, um zur Benutzerabfrage zu gelangen.
                    break

        # Wenn der fehlgeschlagene Schritt der Login war:
        if description == "Login durchführen":
            print("\nLogin ist fehlgeschlagen. Starte Korrektur...")
            letztes_passwort = self.fritzbox.password  # Das zuletzt versuchte Passwort holen

            while True:
                neues_passwort = input(
                    "🔑 Passwort möglicherweise falsch. Bitte erneut eingeben.").strip()

                if neues_passwort == letztes_passwort:
                    print("⚠️ Das eingegebene Passwort ist identisch zum letzten Versuch.")
                    print("🚨 Starte Werksreset über 'Passwort vergessen'...")
                    return self.fritzbox.reset_via_forgot_password()
                else:
                    # Der Benutzer hat ein neues Passwort eingegeben, wir versuchen es damit erneut.
                    print("🔁 Versuche Login mit dem neuen Passwort...")
                    # Wir rufen die Login-Funktion direkt mit dem neuen Passwort auf
                    if self.fritzbox.login(neues_passwort):
                        print("✅ Login mit neuem Passwort war erfolgreich!")
                        return True
                    else:
                        letztes_passwort = neues_passwort


        # Wenn die Schleife beendet ist (nach max_attempts oder explizitem False),
        # fragen wir den Benutzer, was zu tun ist.
        while True:
            auswahl = input(
                "🔁 (W)iederholen, (Ü)berspringen, (B)eenden, (N)eue FritzBox? "
            ).strip().lower()

            if auswahl == "b":
                print("⛔ Vorgang abgebrochen.")
                return False
            elif auswahl == "w":
                # Rekursiver Aufruf für Wiederholung mit Retry-Logik
                return self._run_step_with_retry(description, func, *args, **kwargs)
            elif auswahl == "ü":
                print("⏭️ Schritt übersprungen.")
                return True
            elif auswahl == "n":
                raise RuntimeError("RESTART_NEW_BOX")
            else:
                print("❓ Ungültige Eingabe. Bitte wähle w/ü/b/n.")

    def run_full_workflow(self, password: str) -> str | None:
        """Führt den gesamten FritzBox-Verwaltungs-Workflow mit mehrstufiger Update-Logik aus."""
        # ... (der Anfang der Methode bis zum try-Block bleibt gleich)
        self.browser_driver = setup_browser()
        self.browser = Browser(self.browser_driver)
        self.fritzbox = FritzBox(self.browser)
        self._fenster_in_vordergrund_holen()

        try:
            # Schritte 1-6: Login, Versionen ermitteln, WLAN prüfen, erweiterte Ansicht
            if not self._run_step_with_retry("FritzBox Erreichbarkeit prüfen",
                                             self.fritzbox.warte_auf_erreichbarkeit): return None
            if not self._run_step_with_retry("Login durchführen", self.fritzbox.login, password): return None
            if not self._run_step_with_retry("Firmware-Version ermitteln",
                                             self.fritzbox.get_firmware_version): return None
            if not self._run_step_with_retry("Box-Modell ermitteln", self.fritzbox.get_box_model): return None
            if not self._run_step_with_retry("WLAN-Antennen prüfen", self.fritzbox.check_wlan_antennas): return None
            if not self._run_step_with_retry("Erweiterte Ansicht prüfen/aktivieren",
                                             self.fritzbox.activate_expert_mode_if_needed): return None

            # --- Ab hier die Update-Logik ---
            print("Starte Firmware Update Routine.")

            # KORREKTUR: Robuster Versionsvergleich
            current_version_str = self.fritzbox.os_version or "0.0"
            # Extrahiert die reine Versionsnummer (z.B. "07.57" oder "7.13")
            current_version_match = re.search(r'(\d{1,2}\.\d{2})', current_version_str)
            clean_current_version = current_version_match.group(1) if current_version_match else ""

            major_version = int(clean_current_version.split('.')[0]) if clean_current_version else 0

            model_info = self.firmware_manager.firmware_mapping.get(self.fritzbox.box_model)

            # Fall 1: Mehrstufiges Update
            if major_version < 7 and model_info and "bridge" in model_info:
                print("ℹ️ Mehrstufiges Update erforderlich (alt -> bridge -> final).")
                # ... (die Logik für das mehrstufige Update bleibt hier unverändert)

            # Fall 2: Direktes Update, aber nur wenn die Versionen NICHT übereinstimmen
            elif model_info:
                target_version = model_info.get("final", "")
                if clean_current_version and target_version and clean_current_version.replace("0",
                                                                                              "") == target_version.replace(
                        "0", ""):
                    print(
                        f"✅ Firmware ist bereits auf der Zielversion ({clean_current_version}). Kein Update nötig.")
                else:
                    print(f"ℹ️ Update von {clean_current_version} auf {target_version} wird durchgeführt.")
                    final_path = self.firmware_manager.get_firmware_path(self.fritzbox.box_model, "final")
                    if final_path:
                        update_step = lambda: self.fritzbox.perform_firmware_update(final_path)
                        if not self._run_step_with_retry("Firmware-Update (Final)", update_step): return None
                        # ... (Logik nach dem Update bleibt unverändert) ...
            else:
                print("Keine Update-Regel für dieses Modell gefunden.")

            # Reset als separate Option
            print("Start Workflow für Werkseinstellungen.")
            if not self._run_step_with_retry("Werkseinstellungen über UI",
                                             self.fritzbox.perform_factory_reset_from_ui):
                return None

            # --- NEU: Finale Zusammenfassung des WLAN-Scans anzeigen ---
            if self.fritzbox.wlan_scan_results:
                print("\n\n📡📋 Zusammenfassung des WLAN-Scans 📡📋")
                for i, network_data in enumerate(self.fritzbox.wlan_scan_results):
                    # Rufe die existierende Funktion aus dem FritzBox-Objekt auf
                    # und entpacke die Werte aus dem Dictionary.
                    self.fritzbox.print_wlan_entry(
                        index=i,
                        name=network_data.get("name"),
                        freq=network_data.get("frequency"),
                        channel=network_data.get("channel"),
                        mac=network_data.get("mac"),
                        signal_title=network_data.get("signal")
                    )
                print("--------------------------------------------------")

            print("\n🎉 Workflow für diese FritzBox erfolgreich abgeschlossen!")
            while True:
                auswahl = input("\n(B)eenden oder (N)eue FritzBox bearbeiten? ").strip().lower()
                if auswahl == 'b':
                    return None
                else:
                    return "restart"

        except Exception as e:
            print(f"\n❌ Schwerwiegender Fehler im Workflow")
            return None
        finally:
            if self.browser:
                self.browser.quit()