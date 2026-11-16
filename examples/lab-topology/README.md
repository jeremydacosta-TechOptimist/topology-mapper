# Lab topology fixtures

Four Cisco IOS-style dumps (`show lldp neighbors detail` and
`show cdp neighbors detail`) from a fictional lab, plus an inventory that
declares device roles and management addresses.

All addresses come from the RFC 5737 documentation range (`192.0.2.0/24`) and
host names use the reserved `.example` domain. Nothing here points at a real
network.

| File | Device | Contents |
| --- | --- | --- |
| `core-sw.txt` | `core-sw` (core) | LLDP + CDP detail, four neighbours |
| `floor1-sw.txt` | `floor1-sw` (access) | LLDP + CDP detail, two neighbours |
| `floor2-sw.txt` | `floor2-sw` (access) | LLDP + CDP detail, one neighbour |
| `edge-rtr.txt` | `edge-rtr` (edge) | LLDP + CDP detail, one neighbour |
| `inventory.json` | - | roles and management IPs for the four dumped devices |

The topology is a deliberate lab failure case with these known issues:

1. **Triangle loop** between `core-sw`, `floor1-sw` and `floor2-sw`.
2. **Asymmetric link**: `floor1-sw` reports a link to `floor2-sw` on
   `Gi1/0/2`, but `floor2-sw` has no matching neighbour entry.
3. **Undeclared device**: `fw1` is mentioned by `core-sw` on `Gi1/0/4` and
   has no dump and no inventory entry.

Consequences of that shape: `core-sw` is a single point of failure (removing
it splits the topology) and the report has one error-level finding, so
`topomapper check --dir examples/lab-topology` exits with code 1.

Expected findings:

| ID | Severity | Nodes |
| --- | --- | --- |
| `TOPO-CYCLE` | error | `core-sw`, `floor1-sw`, `floor2-sw` |
| `TOPO-ASYMMETRIC` | warning | `floor1-sw`, `floor2-sw` |
| `TOPO-SPOF` | warning | `core-sw` |
| `TOPO-UNDECLARED` | warning | `fw1` |
