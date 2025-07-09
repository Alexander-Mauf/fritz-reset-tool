# workflow_orchestrator.py
from fritzbox_api import FritzBox, FirmwareManager
from browser_utils import setup_browser, Browser
import time
import win32gui
import win32con
import ctypes

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
            print(f"⚠️ Fenster-Fokus fehlgeschlagen: {e}")

    def _run_step_with_retry(self, description: str, func, *args, **kwargs) -> bool:
        """
        Führt einen einzelnen Schritt aus und bietet Optionen zur Wiederholung/Überspringen bei Fehlern.
        Gibt True zurück, wenn der Schritt erfolgreich war oder übersprungen wurde, False bei Abbruch.
        """
        print(f"\n➡️ {description}...")

        max_attempts = 2
        for attempt in range(max_attempts):
            try:
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

                # Wenn die Funktion True zurückgab (oder None, was wir als Erfolg interpretieren,
                # da die Funktion keine explizite False-Rückgabe hatte), ist der Schritt erfolgreich.
                print("✅ Schritt erfolgreich.")
                return True

            except Exception as e:
                print(f"⚠️ Fehler bei '{description}' (Versuch {attempt + 1}/{max_attempts}): {e}")
                if attempt < max_attempts - 1:
                    print("🔁 Versuche es erneut...")
                    time.sleep(2)
                else:
                    # Nach allen automatischen Versuchen ist der Schritt fehlgeschlagen.
                    # Wir brechen hier aus der Schleife aus, um zur Benutzerabfrage zu gelangen.
                    break

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
            # Schritte 1-5: Login, Versionen ermitteln, WLAN prüfen
            if not self._run_step_with_retry("FritzBox Erreichbarkeit prüfen",
                                             self.fritzbox.warte_auf_erreichbarkeit): return None
            if not self._run_step_with_retry("Login durchführen", self.fritzbox.login, password): return None
            if not self._run_step_with_retry("Firmware-Version ermitteln",
                                             self.fritzbox.get_firmware_version): return None
            if not self._run_step_with_retry("Box-Modell ermitteln", self.fritzbox.get_box_model): return None
            if not self._run_step_with_retry("WLAN-Antennen prüfen", self.fritzbox.check_wlan_antennas): return None
            if not self._run_step_with_retry("Erweiterte Ansicht prüfen/aktivieren",
                                             self.fritzbox.activate_expert_mode_if_needed): return None

            # --- Ab hier die neue Update-Logik ---
            if input("Möchten Sie jetzt nach Updates suchen und diese ggf. durchführen? (j/n): ").lower() != 'j':
                print("Update-Prozess übersprungen.")
                # Optional: Hier könnte man direkt zum Reset springen, wenn gewünscht
            else:
                # Mehrstufige Update-Logik
                current_version_str = self.fritzbox.os_version or "0.0"
                major_version = int(current_version_str.split('.')[0])

                # Fall 1: Version ist alt und benötigt einen Zwischenschritt
                if major_version < 7 and "bridge" in self.firmware_manager.firmware_mapping.get(self.fritzbox.box_model,
                                                                                                {}):
                    print("ℹ️ Mehrstufiges Update erforderlich (alt -> bridge -> final).")

                    # Update auf Bridge-Version
                    print("\n--- Schritt 1: Update auf Bridge-Version ---")
                    bridge_path = self.firmware_manager.get_firmware_path(self.fritzbox.box_model, "bridge")
                    if bridge_path:
                        update_step = lambda: self.fritzbox.perform_firmware_update(bridge_path)
                        if not self._run_step_with_retry("Firmware-Update (Bridge)", update_step): return None

                        print("⏳ Warte 180s auf Neustart...")
                        time.sleep(180)
                        if not self._run_step_with_retry("Erreichbarkeit prüfen (nach Bridge)",
                                                         self.fritzbox.warte_auf_erreichbarkeit, 30, 10): return None
                        if not self._run_step_with_retry("Login (nach Bridge)", self.fritzbox.login, password,
                                                         True): return None
                        self._run_step_with_retry("Version prüfen (nach Bridge)", self.fritzbox.get_firmware_version)
                    else:
                        print("❌ Bridge-Firmware nicht gefunden. Prozess abgebrochen.")
                        return None

                    # Update auf Final-Version (nach erfolgreichem Bridge-Update)
                    print("\n--- Schritt 2: Update auf Final-Version ---")
                    final_path = self.firmware_manager.get_firmware_path(self.fritzbox.box_model, "final")
                    if final_path:
                        update_step = lambda: self.fritzbox.perform_firmware_update(final_path)
                        if not self._run_step_with_retry("Firmware-Update (Final)", update_step): return None

                        print("⏳ Warte 180s auf Neustart...")
                        time.sleep(180)
                        if not self._run_step_with_retry("Erreichbarkeit prüfen (nach Final)",
                                                         self.fritzbox.warte_auf_erreichbarkeit, 30, 10): return None
                        if not self._run_step_with_retry("Login (nach Final)", self.fritzbox.login, password,
                                                         True): return None
                        self._run_step_with_retry("Version prüfen (nach Final)", self.fritzbox.get_firmware_version)
                    else:
                        print("❌ Final-Firmware nicht gefunden. Prozess abgebrochen.")
                        return None

                # Fall 2: Direktes Update auf die finale Version ist möglich
                else:
                    print("ℹ️ Direktes Update auf die finale Version wird geprüft.")
                    final_path = self.firmware_manager.get_firmware_path(self.fritzbox.box_model, "final")
                    if final_path:
                        update_step = lambda: self.fritzbox.perform_firmware_update(final_path)
                        if not self._run_step_with_retry("Firmware-Update (Final)", update_step): return None

                        print("⏳ Warte 180s auf Neustart...")
                        time.sleep(180)
                        if not self._run_step_with_retry("Erreichbarkeit prüfen (nach Final)",
                                                         self.fritzbox.warte_auf_erreichbarkeit, 30, 10): return None
                        if not self._run_step_with_retry("Login (nach Final)", self.fritzbox.login, password,
                                                         True): return None
                        self._run_step_with_retry("Version prüfen (nach Final)", self.fritzbox.get_firmware_version)
                    else:
                        print("❌ Final-Firmware nicht gefunden. Prozess abgebrochen.")
                        return None

            # Reset als separate Option nach dem Update-Prozess
            if input("Möchten Sie die Box zum Abschluss auf Werkseinstellungen zurücksetzen? (j/n): ").lower() == 'j':
                if not self.fritzbox.perform_factory_reset_from_ui():
                    return None

            print("\n🎉 Workflow für diese FritzBox erfolgreich abgeschlossen!")

            # ... (Rest der Methode mit der Abfrage "Beenden" oder "Neue FritzBox" bleibt gleich) ...
            while True:
                auswahl = input("\n(B)eenden oder (N)eue FritzBox bearbeiten? ").strip().lower()
                if auswahl == 'n':
                    return "restart"
                elif auswahl == 'b':
                    return None
        except Exception as e:
            print(f"\n❌ Schwerwiegender Fehler im Workflow: {e}")
            return None
        finally:
            if self.browser:
                self.browser.quit()