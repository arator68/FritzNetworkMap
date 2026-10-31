# FRITZ!Box Network Map Card

Die Karte wird mit der Integration ausgeliefert.

1. Integration installieren/aktualisieren und Home Assistant neu starten.
2. Im Lovelace-Speichermodus wird die Ressource automatisch registriert.
3. Bei `lovelace: resource_mode: yaml` muss die Ressource einmalig in YAML als `type: module` eingetragen werden:
   `/fritz_network_map/fritz-network-map-card.js?v=0.5.23`.
4. Karte hinzufügen -> Manuell und verwenden:

```yaml
type: custom:fritz-network-map-card
entity: sensor.fritz_box_network_map_netzwerk_topologie
title: Netzwerkübersicht
theme: auto
show_labels: true
show_ports: true
colors:
  background: "#111827"
  device: "#263445"
  router: "#2563eb"
  switch: "#0f766e"
  repeater: "#7c3aed"
  online: "#22c55e"
  offline: "#ef4444"
```

Die tatsächliche Entity-ID kann Home Assistant abhängig vom Gerätenamen bilden; bitte in Entwicklerwerkzeuge -> Zustände nach `Netzwerk-Topologie` suchen.
