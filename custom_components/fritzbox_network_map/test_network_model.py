import unittest
from network_model import build_shared_mesh_model, enrich_device_records, validate_mesh_topology, merge_switch_observations, _mesh_client_radio_data
from hosts import merge_wlan_data
from mesh_topology import build_mesh_mac_aliases


class SharedModelTests(unittest.TestCase):
    def test_repeater_radio_signal_uses_both_uplink_interfaces_not_ap_clients(self):
        mesh = {"nodes": [
            {"uid": "master", "device_mac_address": "AA:BB:CC:DD:EE:01", "mesh_role": "master",
             "node_interfaces": []},
            {"uid": "repeater", "device_mac_address": "AA:BB:CC:DD:EE:02", "mesh_role": "slave",
             "node_interfaces": [
                 {"uid": "up-2g", "name": "UPLINK:2G:0", "type": "WLAN", "mac_address": "AA:BB:CC:DD:EE:12",
                  "node_links": [{"uid": "l2", "state": "CONNECTED", "node_1_uid": "master", "node_2_uid": "repeater",
                                   "node_interface_1_uid": "master-2g", "node_interface_2_uid": "up-2g",
                                   "rx_rcpi": -62, "tx_rcpi": -64, "cur_data_rate_rx": 1000, "cur_data_rate_tx": 344100}]},
                 {"uid": "up-5g", "name": "UPLINK:5G:0", "type": "WLAN", "mac_address": "AA:BB:CC:DD:EE:13",
                  "node_links": [{"uid": "l5", "state": "CONNECTED", "node_1_uid": "master", "node_2_uid": "repeater",
                                   "node_interface_1_uid": "master-5g", "node_interface_2_uid": "up-5g",
                                   "rx_rcpi": -76, "tx_rcpi": -61, "cur_data_rate_rx": 576000, "cur_data_rate_tx": 864700}]},
                 {"uid": "ap-2g", "name": "AP:2G:0", "type": "WLAN", "mac_address": "AA:BB:CC:DD:EE:14",
                  "node_links": [{"uid": "client", "state": "CONNECTED", "node_1_uid": "repeater", "node_2_uid": "client-node",
                                   "rx_rcpi": -20, "tx_rcpi": -20}]},
             ]},
        ]}
        model = build_shared_mesh_model(mesh)
        shared = model["devices"]["AA:BB:CC:DD:EE:02"]
        radio = _mesh_client_radio_data(shared, model)
        self.assertEqual(radio["wifi_2_4_signal_rx_dbm"], -62.0)
        self.assertEqual(radio["wifi_2_4_signal_tx_dbm"], -64.0)
        self.assertEqual(radio["wifi_5_signal_rx_dbm"], -76.0)
        self.assertEqual(radio["wifi_5_signal_tx_dbm"], -61.0)
        self.assertEqual(radio["wifi_2_4_speed_mbps"], 344.1)
        self.assertEqual(radio["wifi_5_speed_mbps"], 864.7)

    def test_preserves_all_fields_from_both_json_documents(self):
        mesh = {"schema_version": 1, "nodes": [{
            "uid": "n-master", "device_id": "AA:BB:CC:DD:EE:01",
            "device_mac_address": "AA:BB:CC:DD:EE:01", "mesh_role": "master",
            "vendor_specific": {"extra": 123},
            "node_interfaces": [{"uid": "ni-ap", "name": "AP:5G:0", "type": "WLAN",
                                 "mac_address": "AA:BB:CC:DD:EE:02", "channel": 100}],
        }]}
        lan = {"landevice": [{"mac": "AA:BB:CC:DD:EE:01", "name": "router",
                               "unknown_new_field": "preserve-me",
                               "iplist": [{"entry": {"ip": "192.0.2.1", "addrtype": "IPv4", "custom": True}}]}],
               "future_top_level_field": {"keep": True}}
        model = build_shared_mesh_model(mesh, lan, [{"mac": "AA:BB:CC:DD:EE:01", "wifi": {"band": "5GHz"}}])
        self.assertEqual(model["source_payloads"]["mesh_topology"], mesh)
        self.assertEqual(model["source_payloads"]["landevice"], lan)
        self.assertEqual(model["nodes"]["n-master"]["raw"]["vendor_specific"], {"extra": 123})
        self.assertEqual(model["interfaces"]["ni-ap"]["raw"]["channel"], 100)
        dev = model["devices"]["AA:BB:CC:DD:EE:01"]
        self.assertEqual(dev["landevice_records"][0]["raw"]["unknown_new_field"], "preserve-me")
        self.assertTrue(dev["ip_addresses"][0]["raw"]["custom"])
        self.assertEqual(dev["merged_records"][0]["raw"]["wifi"]["band"], "5GHz")

    def test_resolves_explicit_parent_reference_but_does_not_guess_from_macs(self):
        mesh = {"nodes": [
            {"uid": "master", "device_mac_address": "AA:BB:CC:DD:EE:01", "mesh_role": "master", "node_interfaces": []},
            {"uid": "repeater", "device_mac_address": "AA:BB:CC:DD:EE:02", "mesh_role": "slave",
             "uplink_node_uid": "master", "node_interfaces": []},
            {"uid": "client", "device_mac_address": "AA:BB:CC:DD:EE:03", "mesh_role": "unknown", "node_interfaces": []},
        ]}
        model = build_shared_mesh_model(mesh)
        self.assertEqual(len(model["links"]), 1)
        self.assertEqual(model["links"][0]["source"], "repeater")
        self.assertEqual(model["links"][0]["target"], "master")

    def test_parses_real_fritzbox_node_links_and_deduplicates_link(self):
        mesh = {"nodes": [
            {"uid": "n-master", "device_mac_address": "AA:BB:CC:DD:EE:01", "mesh_role": "master",
             "node_interfaces": [{"uid": "ni-master", "name": "LAN:1", "type": "LAN", "node_links": [
                 {"uid": "nl-1", "type": "LAN", "state": "CONNECTED", "node_1_uid": "n-master",
                  "node_2_uid": "n-switch", "node_interface_1_uid": "ni-master",
                  "node_interface_2_uid": "ni-switch", "learned_via_lldp": True}
             ]}]},
            {"uid": "n-switch", "device_mac_address": "AA:BB:CC:DD:EE:02", "mesh_role": "unknown",
             "node_interfaces": [{"uid": "ni-switch", "name": "gigabitEthernet 1/0/1", "type": "LAN",
                                  "node_links": [{"uid": "nl-1", "type": "LAN", "state": "CONNECTED",
                                                  "node_1_uid": "n-master", "node_2_uid": "n-switch",
                                                  "node_interface_1_uid": "ni-master", "node_interface_2_uid": "ni-switch",
                                                  "learned_via_lldp": True}]}]},
        ]}
        model = build_shared_mesh_model(mesh)
        self.assertEqual(len(model["links"]), 1)
        link = model["links"][0]
        self.assertEqual((link["source"], link["target"]), ("n-master", "n-switch"))
        self.assertEqual((link["source_interface"], link["target_interface"]), ("ni-master", "ni-switch"))
        self.assertEqual(link["state"], "CONNECTED")
        self.assertTrue(link["learned_via_lldp"])
        self.assertEqual(link["evidence"], "fritzbox_node_links")

    def test_topology_validator_reports_missing_refs_and_owner_mismatch(self):
        mesh = {"nodes": [
            {"uid": "master", "node_interfaces": [{"uid": "ni-master", "node_links": [
                {"uid": "nl-good", "state": "CONNECTED", "type": "LAN",
                 "node_1_uid": "master", "node_2_uid": "switch",
                 "node_interface_1_uid": "ni-master", "node_interface_2_uid": "ni-switch"}
            ]}]},
            {"uid": "switch", "node_interfaces": [{"uid": "ni-switch", "node_links": [
                {"uid": "nl-good", "state": "CONNECTED", "type": "LAN",
                 "node_1_uid": "master", "node_2_uid": "switch",
                 "node_interface_1_uid": "ni-master", "node_interface_2_uid": "ni-switch"}
            ]}]},
        ]}
        result = validate_mesh_topology(mesh)
        self.assertEqual(result["raw_link_records"], 2)
        self.assertEqual(result["duplicate_link_ids"], 1)
        self.assertEqual(result["missing_node_reference_records"], 0)
        self.assertEqual(result["missing_interface_reference_records"], 0)
        self.assertEqual(result["interface_owner_mismatch_count"], 0)
        self.assertEqual(result["states"], {"CONNECTED": 2})


    def test_enriches_wlan_client_from_mesh_interface_and_connected_link(self):
        mac = "68:F6:3B:6B:48:0A"
        mesh = {"nodes": [
            {"uid": "n-ap", "device_mac_address": "AA:AA:AA:AA:AA:AA", "mesh_role": "slave",
             "node_interfaces": [{"uid": "ni-ap", "type": "WLAN", "name": "AP:2G:0", "mac_address": "AA:AA:AA:AA:AA:AB",
                                  "node_links": [{"uid": "nl-client", "type": "WLAN", "state": "CONNECTED",
                                                  "node_1_uid": "n-ap", "node_2_uid": "n-client",
                                                  "node_interface_1_uid": "ni-ap", "node_interface_2_uid": "ni-client",
                                                  "cur_data_rate_rx": 0, "cur_data_rate_tx": 6000,
                                                  "rx_rcpi": -55, "tx_rcpi": -48, "last_connected": 123}]}]},
            {"uid": "n-client", "device_mac_address": mac, "mesh_role": "unknown",
             "node_interfaces": [{"uid": "ni-client", "type": "WLAN", "mac_address": mac,
                                  "current_channel": 1,
                                  "current_channel_info": {"channel_width": "20 MHz"},
                                  "node_links": [{"uid": "nl-client", "type": "WLAN", "state": "CONNECTED",
                                                  "node_1_uid": "n-ap", "node_2_uid": "n-client",
                                                  "node_interface_1_uid": "ni-ap", "node_interface_2_uid": "ni-client",
                                                  "cur_data_rate_rx": 0, "cur_data_rate_tx": 6000,
                                                  "rx_rcpi": -55, "tx_rcpi": -48, "last_connected": 123}]}]},
        ]}
        model = build_shared_mesh_model(mesh)
        devices = [{"mac": mac, "name": "Alexa-Schlafzimmer"}]
        enrich_device_records(devices, model)
        alexa = devices[0]
        self.assertEqual(alexa["wifi_2_4_channel"], 1)
        self.assertEqual(alexa["wifi_2_4_channel_width"], 20)
        self.assertEqual(alexa["wifi_2_4_speed_mbps"], 6.0)
        self.assertEqual(alexa["wifi_2_4_signal_rx_dbm"], -55.0)
        self.assertEqual(alexa["wifi_2_4_signal_tx_dbm"], -48.0)
        self.assertEqual(alexa["mesh_wifi_link_uid"], "nl-client")
        self.assertEqual(alexa["mesh_wifi_access_node_uid"], "n-ap")
        # Mesh dBm-like readings must not be mislabeled as a percentage.
        self.assertNotIn("wifi_2_4_signal_strength", alexa)

    def test_enrichment_does_not_replace_existing_fields(self):
        model = build_shared_mesh_model({"nodes": [{"uid": "n", "device_mac_address": "AA:BB:CC:DD:EE:01",
                                                       "mesh_role": "master", "node_interfaces": []}]})
        devices = [{"mac": "aa-bb-cc-dd-ee-01", "name": "existing", "custom": 5}]
        enrich_device_records(devices, model)
        self.assertEqual(devices[0]["name"], "existing")
        self.assertEqual(devices[0]["custom"], 5)
        self.assertEqual(devices[0]["mesh_node_uids"], ["n"])


    def test_repeater_interface_macs_are_merged_into_lanbridge_device(self):
        lanbridge_mac = "BA:FC:7D:AE:37:B9"
        mesh = {"nodes": [{
            "uid": "n-kitchen", "device_mac_address": "B4:FC:7D:AE:37:B7", "mesh_role": "slave",
            "node_interfaces": [
                {"uid": "ni-uplink-2g", "name": "UPLINK:2G:0", "type": "WLAN", "mac_address": "D6:FC:7D:AE:37:B9"},
                {"uid": "ni-uplink-5g", "name": "UPLINK:5G:0", "type": "WLAN", "mac_address": "D6:FC:7D:AE:37:BA"},
                {"uid": "ni-lanbridge", "name": "LANBridge", "type": "LAN", "mac_address": lanbridge_mac},
            ],
        }]}
        devices = [{"mac": lanbridge_mac, "name": "Repeater-Kueche"}]
        aliases = build_mesh_mac_aliases(devices, mesh)
        self.assertEqual(aliases["D6:FC:7D:AE:37:B9"], lanbridge_mac)
        self.assertEqual(aliases["D6:FC:7D:AE:37:BA"], lanbridge_mac)
        merge_wlan_data(devices, [
            {"mac": "D6:FC:7D:AE:37:B9", "wifi_channel": 6, "wifi_speed_mbps": 144},
            {"mac": "D6:FC:7D:AE:37:BA", "wifi_channel": 100, "wifi_speed_mbps": 866},
        ], aliases)
        self.assertEqual(devices[0]["wifi_2_4_channel"], 6)
        self.assertEqual(devices[0]["wifi_2_4_speed_mbps"], 144)
        self.assertEqual(devices[0]["wifi_5_channel"], 100)
        self.assertEqual(devices[0]["wifi_5_speed_mbps"], 866)
        self.assertCountEqual(devices[0]["wlan_mac_aliases"], ["D6:FC:7D:AE:37:B9", "D6:FC:7D:AE:37:BA"])

    def test_repeater_lanbridge_mac_resolves_to_mesh_node_and_parent_link(self):
        repeater_node_mac = "B4:FC:7D:AE:37:B7"
        repeater_lanbridge_mac = "BA:FC:7D:AE:37:B9"
        mesh = {"nodes": [
            {"uid": "n-master", "device_mac_address": "04:B4:FE:18:79:65", "mesh_role": "master",
             "node_interfaces": [{"uid": "ni-master", "name": "AP:5G:0", "type": "WLAN",
                                  "mac_address": "04:B4:FE:18:79:67", "node_links": [
                                      {"uid": "nl-repeater", "type": "WLAN", "state": "CONNECTED",
                                       "node_1_uid": "n-master", "node_2_uid": "n-kitchen",
                                       "node_interface_1_uid": "ni-master", "node_interface_2_uid": "ni-uplink-5g"}
                                  ]}]},
            {"uid": "n-kitchen", "device_mac_address": repeater_node_mac, "mesh_role": "slave",
             "node_interfaces": [
                 {"uid": "ni-uplink-2g", "name": "UPLINK:2G:0", "type": "WLAN", "mac_address": "D6:FC:7D:AE:37:B9"},
                 {"uid": "ni-uplink-5g", "name": "UPLINK:5G:0", "type": "WLAN", "mac_address": "D6:FC:7D:AE:37:BA"},
                 {"uid": "ni-lanbridge", "name": "LANBridge", "type": "LAN", "mac_address": repeater_lanbridge_mac},
                 {"uid": "ni-ap-2g", "name": "AP:2G:0", "type": "WLAN", "mac_address": "B4:FC:7D:AE:37:B9"},
                 {"uid": "ni-ap-5g", "name": "AP:5G:0", "type": "WLAN", "mac_address": "B4:FC:7D:AE:37:BA"},
             ]},
        ]}
        model = build_shared_mesh_model(mesh)
        devices = [{"mac": repeater_lanbridge_mac, "name": "Repeater-Kueche", "device_type": "Repeater",
                    "device_role": "WLAN-Client"}]
        enrich_device_records(devices, model)
        repeater = devices[0]
        self.assertEqual(repeater["mesh_node_uids"], ["n-kitchen"])
        self.assertEqual(repeater["mesh_role"], "slave")
        self.assertEqual(repeater["mesh_direct_connections"][0]["neighbour_name"], "04:B4:FE:18:79:65")

        observations = {repeater_lanbridge_mac: [{"switch_name": "SG3428", "switch_port": "gigabitEthernet 1/0/1"}]}
        merge_switch_observations(model, devices, [], observations, {})
        self.assertEqual(devices[0]["switch_connections"], [])
        self.assertIsNone(devices[0].get("switch_name"))

    def test_repeater_reports_mesh_master_and_collapses_parallel_radio_links(self):
        mesh = {"nodes": [
            {"uid": "n-master", "device_mac_address": "04:B4:FE:18:79:65", "mesh_role": "master",
             "name": "Fritz7590.koch.local", "node_interfaces": [
                 {"uid": "ni-master-2g", "name": "AP:2G:0", "type": "WLAN", "node_links": [
                     {"uid": "nl-2g", "type": "WLAN", "state": "CONNECTED",
                      "node_1_uid": "n-master", "node_2_uid": "n-kitchen",
                      "node_interface_1_uid": "ni-master-2g", "node_interface_2_uid": "ni-kitchen-2g"}
                 ]},
                 {"uid": "ni-master-5g", "name": "AP:5G:0", "type": "WLAN", "node_links": [
                     {"uid": "nl-5g", "type": "WLAN", "state": "CONNECTED",
                      "node_1_uid": "n-master", "node_2_uid": "n-kitchen",
                      "node_interface_1_uid": "ni-master-5g", "node_interface_2_uid": "ni-kitchen-5g"}
                 ]},
             ]},
            {"uid": "n-kitchen", "device_mac_address": "B4:FC:7D:AE:37:B7", "mesh_role": "slave",
             "name": "Repeater-Kueche.koch.local", "node_interfaces": [
                 {"uid": "ni-kitchen-2g", "name": "UPLINK:2G:0", "type": "WLAN", "mac_address": "D6:FC:7D:AE:37:B9"},
                 {"uid": "ni-kitchen-5g", "name": "UPLINK:5G:0", "type": "WLAN", "mac_address": "D6:FC:7D:AE:37:BA"},
             ]},
            {"uid": "n-other", "device_mac_address": "AA:BB:CC:DD:EE:99", "mesh_role": "slave",
             "name": "Other-Repeater", "node_interfaces": []},
        ]}
        # A second edge to another slave is deliberately present: the repeater
        # parent must resolve to the explicitly identified mesh master only.
        mesh["nodes"][2]["node_interfaces"] = [{"uid": "ni-other", "name": "LAN", "type": "LAN", "node_links": [
            {"uid": "nl-other", "type": "LAN", "state": "CONNECTED",
             "node_1_uid": "n-kitchen", "node_2_uid": "n-other",
             "node_interface_1_uid": "ni-kitchen-2g", "node_interface_2_uid": "ni-other"}
        ]}]
        model = build_shared_mesh_model(mesh)
        devices = [{"mac": "B4:FC:7D:AE:37:B7", "name": "Repeater-Kueche", "device_type": "Repeater"}]
        enrich_device_records(devices, model)
        connections = devices[0]["mesh_direct_connections"]
        self.assertEqual(len(connections), 1)
        self.assertEqual(connections[0]["neighbour_name"], "Fritz7590.koch.local")
        self.assertEqual(connections[0]["neighbour_mesh_role"], "master")
        self.assertEqual(len(connections[0]["links"]), 2)

    def test_repeater_is_excluded_from_switch_mapping_even_with_wlan_client_override(self):
        repeater_mac = "BA:FC:7D:AE:37:B9"
        mesh = {"nodes": [{
            "uid": "n-kitchen", "device_mac_address": "B4:FC:7D:AE:37:B7",
            "mesh_role": "slave",
            "node_interfaces": [
                {"uid": "ni-uplink-5g", "name": "UPLINK:5G:0", "type": "WLAN",
                 "mac_address": "D6:FC:7D:AE:37:BA"},
                {"uid": "ni-lanbridge", "name": "LANBridge", "type": "LAN",
                 "mac_address": repeater_mac},
            ],
        }]}
        model = build_shared_mesh_model(mesh)
        devices = [{
            "mac": repeater_mac,
            "name": "Repeater-Kueche",
            "model": "FRITZ!Repeater 1200 AX",
            "device_type": "Repeater",
            "device_role": "WLAN-Client",
        }]
        observations = {repeater_mac: [{
            "switch_name": "SG3428.koch.local",
            "switch_port": "gigabitEthernet 1/0/1",
        }]}

        merge_switch_observations(model, devices, [], observations, {})

        self.assertIn(repeater_mac, model["switch_mac_table"])
        self.assertEqual(devices[0]["switch_connections"], [])
        self.assertIsNone(devices[0].get("switch_name"))
        self.assertIsNone(devices[0].get("switch_port"))
        self.assertIn("Mesh-Infrastruktur", devices[0]["switch_connection_excluded_reason"])

    def test_repeater_role_is_excluded_from_switch_mapping(self):
        repeater_mac = "BA:FC:7D:AE:37:B9"
        model = build_shared_mesh_model({"nodes": []})
        devices = [{
            "mac": repeater_mac,
            "name": "Repeater-Kueche",
            "device_type": "Repeater",
            "device_role": "Repeater",
        }]
        observations = {repeater_mac: [{
            "switch_name": "SG3428.koch.local",
            "switch_port": "gigabitEthernet 1/0/1",
        }]}

        merge_switch_observations(model, devices, [], observations, {})

        self.assertEqual(devices[0]["switch_connections"], [])
        self.assertIsNone(devices[0].get("switch_name"))
        self.assertIsNone(devices[0].get("switch_port"))

    def test_wlan_client_is_excluded_from_per_device_switch_connection(self):
        mac = "98:CC:F3:FD:A8:43"
        model = build_shared_mesh_model({"nodes": []}, {"landevice": [{"mac": mac, "name": "Alexa-Wohnzimmer"}]})
        devices = [{"mac": mac, "name": "Alexa-Wohnzimmer", "device_role": "WLAN-Client"}]
        observations = {mac: [{"switch_name": "SG3428.koch.local", "switch_host": "192.168.178.84", "switch_port": "gigabitEthernet 1/0/1", "switch_vlan_id": 1}]}
        merged = merge_switch_observations(model, devices, [{"name": "SG3428.koch.local", "host": "192.168.178.84", "port": 161}], observations, {})
        self.assertIn(mac, merged["switch_mac_table"])
        self.assertEqual(devices[0]["switch_connections"], [])
        self.assertIsNone(devices[0]["switch_name"])
        self.assertIsNone(devices[0]["switch_port"])
        self.assertEqual(devices[0]["switch_connection_excluded_reason"], "WLAN-Client: kein direkter Ethernet-Anschluss")

    def test_wired_device_keeps_switch_connection(self):
        mac = "90:09:D0:79:05:43"
        model = build_shared_mesh_model({"nodes": []}, {"landevice": [{"mac": mac, "name": "SynologyNAS"}]})
        devices = [{"mac": mac, "name": "SynologyNAS", "device_role": "LAN-Client"}]
        observations = {mac: [{"switch_name": "SG3428.koch.local", "switch_host": "192.168.178.84", "switch_port": "gigabitEthernet 1/0/3", "switch_vlan_id": 1}]}
        merge_switch_observations(model, devices, [{"name": "SG3428.koch.local", "host": "192.168.178.84", "port": 161}], observations, {})
        self.assertEqual(devices[0]["switch_port"], "gigabitEthernet 1/0/3")
        self.assertEqual(len(devices[0]["switch_connections"]), 1)

    def test_switch_observations_join_shared_model_by_normalized_mac(self):
        nas_mac = "90:09:D0:79:05:43"
        model = build_shared_mesh_model({"nodes": []}, {"landevice": [{"mac": nas_mac, "name": "SynologyNAS"}]})
        devices = [{"mac": "90-09-d0-79-05-43", "name": "SynologyNAS", "direct_connection": "fritz.box"}]
        observations = {nas_mac: [{"switch_name": "TL-SG3428", "switch_host": "192.168.178.84", "switch_port": "gigabitEthernet 1/0/3", "switch_bridge_port": 3, "switch_if_index": 3}]}
        merged = merge_switch_observations(model, devices, [{"name": "TL-SG3428", "host": "192.168.178.84", "port": 161}], observations, {})
        self.assertIn("192.168.178.84", merged["switches"])
        self.assertEqual(merged["switch_mac_table"][nas_mac][0]["switch_port"], "gigabitEthernet 1/0/3")
        self.assertEqual(merged["devices"][nas_mac]["switch_observations"][0]["switch_name"], "TL-SG3428")
        self.assertEqual(devices[0]["switch_name"], "TL-SG3428")
        self.assertEqual(merged["switch_links"][0]["relationship"], "learned_on_port_not_proven_direct_attachment")


    def test_repeater_lanbridge_override_gets_both_uplink_signal_bands(self):
        lanbridge_mac = "BA:FC:7D:AE:37:B9"
        mesh = {"nodes": [
            {"uid": "master", "device_mac_address": "04:B4:FE:18:79:65", "mesh_role": "master",
             "name": "fritz.box", "node_interfaces": []},
            {"uid": "kitchen", "device_mac_address": "B4:FC:7D:AE:37:B7", "mesh_role": "slave",
             "name": "Repeater-Kueche.koch.local", "node_interfaces": [
                 {"uid": "uplink-2g", "name": "UPLINK:2G:0", "type": "WLAN", "mac_address": "D6:FC:7D:AE:37:B9",
                  "node_links": [{"uid": "nl-520", "state": "CONNECTED", "node_1_uid": "master", "node_2_uid": "kitchen",
                                   "node_interface_1_uid": "master-2g", "node_interface_2_uid": "uplink-2g",
                                   "rx_rcpi": -62, "tx_rcpi": -64, "cur_data_rate_rx": 1000, "cur_data_rate_tx": 344100}]},
                 {"uid": "uplink-5g", "name": "UPLINK:5G:0", "type": "WLAN", "mac_address": "D6:FC:7D:AE:37:BA",
                  "node_links": [{"uid": "nl-410", "state": "CONNECTED", "node_1_uid": "master", "node_2_uid": "kitchen",
                                   "node_interface_1_uid": "master-5g", "node_interface_2_uid": "uplink-5g",
                                   "rx_rcpi": -76, "tx_rcpi": -61, "cur_data_rate_rx": 576000, "cur_data_rate_tx": 864700}]},
                 {"uid": "lanbridge", "name": "LANBridge", "type": "LAN", "mac_address": lanbridge_mac},
             ]},
        ]}
        model = build_shared_mesh_model(mesh)
        devices = [{"mac": lanbridge_mac, "name": "Repeater-Kueche", "device_type": "Repeater", "device_role": "WLAN-Client"}]
        enrich_device_records(devices, model)
        repeater = devices[0]
        self.assertEqual(repeater["mesh_node_uids"], ["kitchen"])
        self.assertEqual(repeater["wifi_2_4_signal_rx_dbm"], -62.0)
        self.assertEqual(repeater["wifi_2_4_signal_tx_dbm"], -64.0)
        self.assertEqual(repeater["wifi_5_signal_rx_dbm"], -76.0)
        self.assertEqual(repeater["wifi_5_signal_tx_dbm"], -61.0)

if __name__ == "__main__":
    unittest.main()
