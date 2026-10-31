FRITZ!Box Network Map – Geräteklassifizierung

Dateien:
- mac_vendors.csv: lokale IEEE-Herstellerdatenbank; wird mit build_mac_vendor_db.py befüllt.
- device_overrides.csv: deine manuell editierbare Gerätedatenbank.
- mac_vendor.py: Hersteller-Lookup mit längstem passenden Präfix.
- device_overrides.py: lädt manuelle Zuordnungen.
- fritzbox_client.py und sensor.py: Integration der Daten und Diagnose-Sensoren.

device_overrides.csv mit LibreOffice Calc, Excel oder einem Texteditor bearbeiten.
Spalten:
mac,hostname,model,device_type,device_role,notes

Priorität der Zuordnung:
1. Exakte MAC-Adresse
2. Exakter Hostname (FRITZ!Box-Name oder Friendly Name)
3. Exakte Modellangabe

Beispielzeilen (nur Beispiele, nicht echte Geräte):
AA:BB:CC:11:22:33,,TL-SG3428,Switch,Switch,Manuell bestätigt
,,Beispielkamera, Kamera,,Manuell zugeordnet

Wichtig: Bei Modell-/Hostname-Zuordnungen gilt die Regel für alle Geräte, die exakt passen.
Für einzelne Geräte daher bevorzugt die MAC-Adresse eintragen. Nach Änderungen Home Assistant neu starten, damit die CSV neu eingelesen wird.

Herstellerdatenbank einmalig/bei Aktualisierung befüllen:
python3 /config/custom_components/fritzbox_network_map/build_mac_vendor_db.py

Die bisherige Mesh-, WLAN-, LAN- und Herstellerdiagnose bleibt im fritzbox_client.py erhalten.
