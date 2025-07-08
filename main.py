# main.py
from workflow_orchestrator import WorkflowOrchestrator
import time

def main():
    """
    Hauptfunktion des Programms zur Verwaltung von FritzBoxen.
    Initialisiert den Workflow und steuert die Wiederholung des Prozesses.
    """
    print("🚀 Starte FritzBox-Verwaltungsprogramm...")

    # Instanz des Workflow-Orchestrators erstellen
    orchestrator = WorkflowOrchestrator()

    try:
        while True:
            # Passwort vorab abfragen, da es für den Login benötigt wird
            password = input("🔑 FritzBox-Passwort eingeben: ").strip()
            if not password:
                print("❌ Passwort darf nicht leer sein. Bitte erneut versuchen.")
                continue

            # Starte den vollständigen Workflow
            # Der WorkflowOrchestrator gibt "restart" zurück, wenn der Benutzer dies wünscht.
            result = orchestrator.run_full_workflow(password)

            if result == "restart":
                print("\n🔁 Starte den Workflow für eine neue FritzBox...")
                # Die orchestrator-Instanz kann wiederverwendet werden, da sie den Browser am Ende beendet.
                # Bei einem "restart" wird im orchestrator ein neuer Browser und FritzBox-Objekt erstellt.
                continue
            else:
                # Workflow beendet oder abgebrochen
                print("🏁 Vorgang abgeschlossen.")
                break

    except Exception as e:
        print(f"\n catastrophic_error: Ein unerwarteter Fehler ist aufgetreten: {e}")
        print("Das Programm wird in 15 Sekunden beendet.")
        time.sleep(15)

if __name__ == "__main__":
    main()