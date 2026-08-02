"""
Parser for platform / inventory / version output.
Multi-vendor: Cisco IOS/IOS-XE/NX-OS, Arista EOS, Juniper JunOS,
Palo Alto PAN-OS, F5 BIG-IP, Fortinet FortiOS, Check Point, A10, Citrix.
"""
import re
from typing import Optional


def parse_platform_detail(raw_text: str, local_hostname: Optional[str] = None) -> dict:
    """
    Parse platform/inventory information from any vendor.
    Returns a device info dictionary with model, serial, software, etc.
    """
    info = {
        "hostname": local_hostname or "",
        "model": "",
        "serial": "",
        "software_version": "",
        "platform": "",
        "vendor": "",
        "uptime": "",
        "interfaces_count": 0,
    }

    hostname_match = re.search(r"(\S+)\s*[#>]", raw_text)
    if hostname_match and not local_hostname:
        info["hostname"] = hostname_match.group(1).strip()

    info["model"] = _extract_model(raw_text)
    info["serial"] = _extract_serial(raw_text)
    info["software_version"] = _extract_version(raw_text)
    info["platform"] = _extract_platform(raw_text)
    info["vendor"] = _detect_vendor(raw_text, info["model"], info["platform"])

    uptime_match = re.search(
        r"(?:uptime is|System uptime|Uptime|Kernel uptime)\s*:?\s+(.+)",
        raw_text, re.IGNORECASE
    )
    if uptime_match:
        info["uptime"] = uptime_match.group(1).strip()

    info["device_role"] = _infer_device_role(
        info["model"], info["platform"], info["hostname"] or local_hostname or "", raw_text
    )

    return info


def _extract_model(raw_text: str) -> str:
    """Extract model number across vendors."""
    patterns = [
        # Cisco: Model Number, Model number, PID
        r"[Mm]odel\s*(?:[Nn]umber)?\s*:\s*(\S+)",
        r"PID:\s*(\S+)",
        # Cisco show version: "cisco Nexus9000 ..." or "cisco WS-C3750X-48P"
        r"[Cc]isco\s+((?:Nexus|Catalyst|N\d+K|WS-|C\d+|ASR|ISR|ASA|FPR)[\w-]+)",
        # Arista: Arista DCS-7050TX-48
        r"[Aa]rista\s+([\w-]+)",
        # Juniper: Model: ex4300-48t
        r"[Mm]odel:\s*([\w-]+)",
        # Palo Alto: Model: PA-5250
        r"model:\s*(PA-[\w-]+)",
        # Fortinet: FortiGate-600E
        r"(FortiGate-[\w-]+|FG[\w-]+)",
        # F5: BIG-IP i5800 / BIG-IP Virtual Edition
        r"(BIG-IP[\w\s-]+?)(?:\n|$)",
        # A10: Thunder 3030S
        r"(Thunder[\w\s-]+?)(?:\n|$)",
        # Citrix ADC / NetScaler
        r"(NetScaler[\w\s-]*|Citrix ADC[\w\s-]*?)(?:\n|$)",
        # Check Point: Check Point 5400
        r"(Check\s*Point[\w\s-]*?)(?:\n|$)",
        # Generic NAME: "chassis" ... PID:
        r'NAME:\s*"[Cc]hassis".*?PID:\s*(\S+)',
        # Generic fallback
        r"cisco\s+([\w-]+)\s",
    ]
    for pat in patterns:
        m = re.search(pat, raw_text, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return ""


def _extract_serial(raw_text: str) -> str:
    """Extract serial number across vendors."""
    patterns = [
        r"[Ss]erial\s*[Nn]umber?\s*:\s*(\S+)",
        r"\bSN:\s*(\S+)",
        r"System serial number\s*:\s*(\S+)",
        r"Processor board ID\s+(\S+)",
        # Juniper
        r"Chassis\s+\S+\s+(\S+)\s+",
        # Palo Alto
        r"serial:\s*(\S+)",
        # F5
        r"Chassis Serial Number\s*:\s*(\S+)",
        # Fortinet
        r"Serial-Number:\s*(\S+)",
    ]
    for pat in patterns:
        m = re.search(pat, raw_text, re.IGNORECASE)
        if m:
            val = m.group(1).strip()
            if len(val) >= 4:
                return val
    return ""


def _extract_version(raw_text: str) -> str:
    """Extract software version across vendors."""
    patterns = [
        # Cisco IOS/IOS-XE/NX-OS
        r"(?:Cisco IOS|IOS-XE|NXOS|NX-OS|system:\s*version)\s*(?:Software)?[,\s]*[Vv]ersion\s+(\S+)",
        r"System version:\s*(\S+)",
        r"NXOS:\s*version\s+(\S+)",
        # Arista EOS
        r"Software image version:\s*(\S+)",
        r"EOS\s+version\s*[:=]?\s*(\S+)",
        r"Arista.*?EOS.*?(\d+\.\d+\S*)",
        # Juniper JunOS
        r"JUNOS\s+\S+\s+\[(\S+)\]",
        r"Junos:\s*(\S+)",
        # Palo Alto PAN-OS
        r"sw-version:\s*(\S+)",
        r"PAN-OS\s+(\S+)",
        # Fortinet FortiOS
        r"Firmware Version\s*:\s*v?(\S+)",
        r"FortiOS\s*v?(\S+)",
        # F5 BIG-IP
        r"BIG-IP\s+(\d+\.\d+\S*)",
        r"Version\s+(\d+\.\d+\.\d+\S*)",
        # Check Point
        r"Product version\s+(?:Check Point )?(R\S+)",
        # Generic
        r"Software.*?[Vv]ersion\s+(\S+)",
    ]
    for pat in patterns:
        m = re.search(pat, raw_text, re.IGNORECASE)
        if m:
            return m.group(1).strip().rstrip(",")
    return ""


def _extract_platform(raw_text: str) -> str:
    """Extract platform description."""
    patterns = [
        r"(?:[Cc]isco|Arista|Juniper|Palo Alto|Fortinet|F5)\s+(\S+.*?)(?:\s+\(|$)",
        r"Hardware:\s*(.+?)(?:\n|$)",
        r"Hardware model:\s*(.+?)(?:\n|$)",
    ]
    for pat in patterns:
        m = re.search(pat, raw_text, re.IGNORECASE)
        if m:
            return m.group(1).strip()[:80]
    return ""


def _detect_vendor(raw_text: str, model: str, platform: str) -> str:
    """Detect device vendor from text, model, and platform fields."""
    combined = f"{raw_text[:4000]} {model} {platform}".lower()

    vendor_signals = [
        (["cisco", "nexus", "nx-os", "ios-xe", "ios-xr", "catalyst", "ws-c", "n9k", "n7k", "n5k", "n3k", "asr", "isr", "asa", "fpr", "ftd", "meraki"], "Cisco"),
        (["arista", "eos", "dcs-", "veos"], "Arista"),
        (["juniper", "junos", "ex4", "ex3", "qfx", "mx-", "srx", "mx9"], "Juniper"),
        (["palo alto", "panos", "pa-", "panorama"], "Palo Alto"),
        (["fortinet", "fortigate", "fortios", "fg-", "fgt-"], "Fortinet"),
        (["f5", "big-ip", "bigip", "tmsh", "ltm", "gtm"], "F5"),
        (["a10", "thunder", "acos"], "A10"),
        (["citrix", "netscaler", "adc"], "Citrix"),
        (["check point", "checkpoint", "gaia", "cpuse", "smartconsole"], "Check Point"),
        (["huawei", "vrp", "ce6", "ce8", "s57", "s67", "ne40"], "Huawei"),
        (["dell", "force10", "os10", "os9", "powerswitch"], "Dell"),
        (["hpe", "aruba", "procurve", "comware"], "HPE/Aruba"),
        (["extreme", "exos", "x4"], "Extreme"),
        (["brocade", "fabric os", "vdx"], "Brocade"),
    ]

    for signals, vendor_name in vendor_signals:
        for sig in signals:
            if sig in combined:
                return vendor_name

    return "Unknown"


def _infer_device_role(model: str, platform: str, hostname: str, raw_text: str) -> str:
    """
    Infer device role from model, platform, hostname, and full text.
    Returns: spine, leaf, router, firewall, loadbalancer, wlc, border, endpoint, switch.
    """
    hn_lower = hostname.lower() if hostname else ""
    combined = f"{model} {platform}".lower()
    text_lower = raw_text[:3000].lower()

    # --- Hostname-based detection (highest priority) ---
    hostname_roles = [
        (["fw", "firewall", "asa", "ftd", "palo", "pan", "forti", "checkpoint", "chkp"], "firewall"),
        (["lb", "loadbal", "f5", "bigip", "big-ip", "netscaler", "citrix", "a10", "thunder"], "loadbalancer"),
        (["rtr", "router", "gw", "gateway"], "router"),
        (["spine", "core"], "spine"),
        (["leaf", "access", "edge", "tor"], "leaf"),
        (["border", "bgw", "dcgw"], "border"),
        (["wlc", "wireless", "wifi", "wlan"], "wlc"),
    ]
    for keywords, role in hostname_roles:
        if any(k in hn_lower for k in keywords):
            return role

    # --- Model/platform-based detection ---

    # Firewalls
    firewall_patterns = [
        "asa", "ftd", "fpr", "firepower",
        "pa-", "pan-", "palo",
        "fortigate", "fg-", "fg1", "fg2", "fg3", "fg4", "fg5", "fg6",
        "checkpoint", "check point",
        "srx",  # Juniper SRX
        "vsrx",
    ]
    if any(k in combined for k in firewall_patterns):
        return "firewall"

    # Load balancers
    lb_patterns = [
        "big-ip", "bigip", "f5", "ltm", "gtm",
        "netscaler", "citrix adc", "mpx", "vpx", "sdx",
        "a10", "thunder",
        "alteon",
        "kemp",
        "haproxy",
        "ace-",  # Cisco ACE
    ]
    if any(k in combined for k in lb_patterns):
        return "loadbalancer"

    # Routers
    router_patterns = [
        "asr", "isr", "csr", "ncs", "xrv",
        "nexus 7", "n7k", "n77",
        "mx-", "mx80", "mx104", "mx204", "mx240", "mx480", "mx960",  # Juniper MX
        "ptx",  # Juniper PTX
        "7750", "7250",  # Nokia
    ]
    if any(k in combined for k in router_patterns):
        return "router"

    # WLC
    wlc_patterns = ["wlc", "air-ct", "c9800", "wireless", "3504", "5520", "8540"]
    if any(k in combined for k in wlc_patterns):
        return "wlc"

    # Spine/Core switches
    spine_patterns = [
        "9500", "9400", "6500", "6800", "6880", "7700", "7710", "7009", "7010", "7018",
        "n9k", "n7k", "n77", "n5k", "n6k",
        "nexus 9", "nexus 7", "nexus 5", "nexus 6",
        "dcs-7500", "dcs-7300", "dcs-7280",  # Arista high-end
        "qfx10", "qfx5",  # Juniper QFX
        "ex9",  # Juniper EX9200
    ]
    if any(k in combined for k in spine_patterns):
        return "spine"

    # Leaf/Access switches
    leaf_patterns = [
        "9300", "9200", "3850", "3750", "3650", "3560", "2960",
        "c9300", "c9200", "c3850", "c3750",
        "ws-c", "ws-c29", "ws-c37", "ws-c38",
        "n3k", "n2k", "nexus 3", "nexus 2",
        "dcs-7050", "dcs-7020", "dcs-7010",  # Arista leaf-class
        "ex4", "ex3", "ex2",  # Juniper EX
        "icx", "fastiron",  # Brocade/Ruckus
        "dell emc", "powerswitch", "s5", "s4", "s3",  # Dell
        "comware", "flexfabric",  # HPE
    ]
    if any(k in combined for k in leaf_patterns):
        return "leaf"

    # Border
    if any(k in combined for k in ["border", "bgw", "dcgw"]):
        return "border"

    # --- Text-content-based fallback ---
    if any(k in text_lower for k in ["firewall", "security-zone", "rulebase", "security policy"]):
        return "firewall"
    if any(k in text_lower for k in ["ltm", "virtual-server", "pool member", "load-balanc"]):
        return "loadbalancer"
    if any(k in text_lower for k in ["router ospf", "router bgp", "router isis"]):
        if "switchport" not in text_lower:
            return "router"

    return "switch"
