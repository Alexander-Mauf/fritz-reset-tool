from fritz_steps import (
    get_steps_from_branding,
    beende_browser
)

import win32gui
import win32con
import ctypes

import tkinter as tk
from tkinter import filedialog

def dateipfad_auswählen():
    root = tk.Tk()
    root.withdraw()
    return filedialog.askopenfilename(title="Firmware-Datei auswählen", filetypes=[("Firmware Image", "*.image")])

def fenster_in_vordergrund_holen():
    try:
        hwnd = win32gui.GetForegroundWindow()
        console_hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        win32gui.ShowWindow(console_hwnd, win32con.SW_SHOWNORMAL)
        win32gui.SetForegroundWindow(console_hwnd)
        print("🪟 CMD-Fenster wurde in den Vordergrund gebracht.")
    except Exception as e:
        print(f"⚠️ Fenster-Fokus fehlgeschlagen: {e}")
from browser_utils import setup_browser


def run_step_with_retry(driver, description, func):
    print(f"\n➡️ {description}...")

    for attempt in range(2):
        try:
            func(driver)
            print("✅ Schritt erfolgreich.")
            return True
        except Exception as e:
            print(f"⚠️ Fehler bei '{description}': {e}")
            if attempt == 0:
                print("🔁 Versuche es erneut...")
            else:
                break

    while True:
        auswahl = input("🔁 (W)iederholen, (Ü)berspringen, (B)eenden, (N)eue FritzBox? ").strip().lower()
        if auswahl == "b":
            print("⛔ Vorgang abgebrochen.")
            return False
        elif auswahl == "w":
            return run_step_with_retry(driver, description, func)
        elif auswahl == "ü":
            print("⏭️ Schritt übersprungen.")
            return True
        elif auswahl == "n":
            raise RuntimeError("RESTART_NEW_BOX")
        else:
            print("❓ Ungültige Eingabe. Bitte wähle w/ü/b/n.")


def run_workflow(password, firmware_pfad):
    driver = setup_browser()
    fenster_in_vordergrund_holen()

    try:
        steps = get_steps_from_branding(driver, password, firmware_pfad)

        for beschreibung, funktion in steps:
            if not run_step_with_retry(driver, beschreibung, funktion):
                break

    except RuntimeError as e:
        if str(e) == "RESTART_NEW_BOX":
            beende_browser(driver)
            return "restart"
        else:
            print(f"❌ Unerwarteter Fehler: {e}")
    except Exception as e:
        print(f"\n❌ Schwerwiegender Fehler im Ablauf: {e}")
    finally:
        beende_browser(driver)
