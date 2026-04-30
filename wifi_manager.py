from __future__ import annotations

import html
import os
import re
import socket
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from profile_store import WifiProfile


class WifiError(RuntimeError):
    pass


@dataclass(slots=True)
class WifiNetwork:
    ssid: str
    authentication: str = ""
    encryption: str = ""
    signal: str = ""


@dataclass(slots=True)
class WifiStatus:
    connected: bool
    ssid: str = ""
    interface_name: str = ""
    state: str = ""
    radio_on: bool | None = None
    message: str = ""

    @property
    def label(self) -> str:
        if self.connected and self.ssid:
            return f"Connected: {self.ssid}"
        if self.message:
            return self.message
        return "Disconnected"


@dataclass(slots=True)
class ConnectivityResult:
    target: str
    host: str
    online: bool
    details: list[str] = field(default_factory=list)


class WifiManager:
    def __init__(self, timeout: int = 25) -> None:
        self.timeout = timeout

    def run_netsh(self, args: list[str], timeout: int | None = None) -> str:
        command = ["netsh", *args]
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout or self.timeout,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        except FileNotFoundError as exc:
            raise WifiError("netsh was not found. This app must run on Windows.") from exc
        except subprocess.TimeoutExpired as exc:
            raise WifiError("The netsh command timed out. WLAN service may be busy.") from exc
        except OSError as exc:
            raise WifiError(f"Could not run netsh: {exc}") from exc

        output = (completed.stdout or "") + (completed.stderr or "")
        if completed.returncode != 0:
            raise WifiError(self._friendly_netsh_error(output))
        return output

    def scan_networks(self) -> list[WifiNetwork]:
        output = self.run_netsh(["wlan", "show", "networks", "mode=bssid"], timeout=35)
        networks: list[WifiNetwork] = []
        current: WifiNetwork | None = None

        for raw_line in output.splitlines():
            line = raw_line.strip()
            key, value = self._split_key_value(line)
            lower_key = key.lower()

            ssid_match = re.match(r"^SSID\s+\d+$", key, re.IGNORECASE)
            if ssid_match:
                if current and current.ssid:
                    networks.append(current)
                current = WifiNetwork(ssid=value)
                continue

            if not current:
                continue

            if lower_key in {"authentication"}:
                current.authentication = value
            elif lower_key in {"encryption"}:
                current.encryption = value
            elif lower_key in {"signal"} and not current.signal:
                current.signal = value

        if current and current.ssid:
            networks.append(current)

        unique: dict[str, WifiNetwork] = {}
        for network in networks:
            unique.setdefault(network.ssid, network)
        return sorted(unique.values(), key=lambda item: item.ssid.casefold())

    def get_status(self) -> WifiStatus:
        try:
            output = self.run_netsh(["wlan", "show", "interfaces"], timeout=12)
        except WifiError as exc:
            return WifiStatus(False, message=str(exc))

        blocks = self._interface_blocks(output)
        best_status = WifiStatus(False, message="Disconnected")

        for block in blocks:
            data = self._parse_block(block)
            state = data.get("state", "")
            ssid = data.get("ssid", "")
            interface_name = data.get("name", "")
            radio_on = self._radio_state(data)
            connected = self._looks_connected(state) and bool(ssid)

            status = WifiStatus(
                connected=connected,
                ssid=ssid,
                interface_name=interface_name,
                state=state,
                radio_on=radio_on,
                message=self._status_message(state, radio_on),
            )
            if connected:
                return status
            if interface_name and not best_status.interface_name:
                best_status = status

        return best_status

    def ensure_profile(self, profile: WifiProfile) -> None:
        if self.profile_exists(profile.ssid):
            return

        xml_text = self._build_profile_xml(profile)
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                delete=False,
                suffix=".xml",
                encoding="utf-8",
            ) as file:
                file.write(xml_text)
                temp_path = Path(file.name)

            try:
                self.run_netsh(
                    ["wlan", "add", "profile", f"filename={str(temp_path)}", "user=current"],
                    timeout=20,
                )
            except WifiError as exc:
                if self._is_existing_profile_error(str(exc)):
                    return
                raise
        finally:
            if temp_path:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass

    def profile_exists(self, profile_name: str) -> bool:
        names = self.saved_profile_names()
        wanted = profile_name.strip().casefold()
        return any(name.strip().casefold() == wanted for name in names)

    def saved_profile_names(self) -> list[str]:
        output = self.run_netsh(["wlan", "show", "profiles"], timeout=12)
        names: list[str] = []
        for raw_line in output.splitlines():
            line = raw_line.strip()
            key, value = self._split_key_value(line)
            lower_key = key.lower()
            if value and ("profile" in lower_key) and ("profiles on interface" not in lower_key):
                names.append(value)
        return names

    def connect(self, profile: WifiProfile, wait_seconds: int = 15) -> WifiStatus:
        self.ensure_profile(profile)
        self.run_netsh(
            ["wlan", "connect", f"name={profile.ssid}", f"ssid={profile.ssid}"],
            timeout=20,
        )

        deadline = time.time() + wait_seconds
        last_status = self.get_status()
        while time.time() < deadline:
            last_status = self.get_status()
            if last_status.connected and last_status.ssid == profile.ssid:
                return last_status
            time.sleep(1)

        if last_status.connected:
            raise WifiError(
                f"Connected to {last_status.ssid}, not {profile.ssid}. "
                "The password may be wrong or Windows selected another network."
            )
        raise WifiError(
            f"Could not connect to {profile.ssid}. Check Wi-Fi power, password, range, "
            "and WLAN AutoConfig service."
        )

    def can_reach_target(self, target: str, timeout_seconds: int = 45) -> bool:
        return self.check_connectivity(target, timeout_seconds).online

    def check_connectivity(self, target: str, timeout_seconds: int = 45) -> ConnectivityResult:
        host = self._normalize_ping_target(target)
        if not host:
            return ConnectivityResult(target=target, host="", online=False, details=["No ping target set."])

        timeout_seconds = max(1, min(int(timeout_seconds), 600))
        details = [f"Target: {target}", f"Host: {host}", f"Ping timeout: {timeout_seconds}s"]
        ping_ok, ping_details = self._ping_host(host, timeout_seconds)
        details.extend(ping_details)
        if ping_ok:
            return ConnectivityResult(target=target, host=host, online=True, details=details)

        tcp_ok, tcp_details = self._tcp_probe(host)
        details.extend(tcp_details)
        return ConnectivityResult(target=target, host=host, online=tcp_ok, details=details)

    def _ping_host(self, host: str, timeout_seconds: int) -> tuple[bool, list[str]]:
        timeout_ms = timeout_seconds * 1000
        started = time.monotonic()
        try:
            completed = subprocess.run(
                ["ping", "-n", "1", "-w", str(timeout_ms), host],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_seconds + 5,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        except subprocess.TimeoutExpired:
            elapsed = time.monotonic() - started
            return False, [
                f"Ping timed out after {timeout_seconds} seconds.",
                f"Ping elapsed: {elapsed:.1f}s",
            ]
        except OSError as exc:
            return False, [f"Ping failed to start: {exc}"]

        elapsed = time.monotonic() - started
        output = (completed.stdout or "") + (completed.stderr or "")
        summary = " ".join(line.strip() for line in output.splitlines() if line.strip())
        if len(summary) > 260:
            summary = summary[:257] + "..."
        return completed.returncode == 0, [
            f"Ping exit code: {completed.returncode}",
            f"Ping elapsed: {elapsed:.1f}s",
            f"Ping output: {summary or '(empty)'}",
        ]

    def _tcp_probe(self, host: str) -> tuple[bool, list[str]]:
        details: list[str] = []
        for port in (443, 80):
            try:
                with socket.create_connection((host, port), timeout=3):
                    details.append(f"TCP {host}:{port} connected.")
                    return True, details
            except OSError as exc:
                details.append(f"TCP {host}:{port} failed: {exc}")
                continue
        return False, details

    def restart_adapter(self) -> None:
        status = self.get_status()
        interface_name = status.interface_name or self._first_wireless_interface_name()
        if not interface_name:
            raise WifiError("No Wi-Fi adapter was found to restart.")

        self.run_netsh(
            ["interface", "set", "interface", f'name="{interface_name}"', "admin=disabled"],
            timeout=20,
        )
        time.sleep(2)
        self.run_netsh(
            ["interface", "set", "interface", f'name="{interface_name}"', "admin=enabled"],
            timeout=20,
        )

    def _first_wireless_interface_name(self) -> str:
        output = self.run_netsh(["wlan", "show", "interfaces"], timeout=12)
        for raw_line in output.splitlines():
            key, value = self._split_key_value(raw_line.strip())
            if key.lower() == "name" and value:
                return value
        return ""

    def _build_profile_xml(self, profile: WifiProfile) -> str:
        ssid_hex = profile.ssid.encode("utf-8").hex().upper()
        escaped_ssid = html.escape(profile.ssid, quote=True)
        escaped_password = html.escape(profile.password, quote=True)
        auth = "WPA3SAE" if profile.security_type == "WPA3-Personal" else "WPA2PSK"

        shared_key = ""
        if profile.password:
            shared_key = f"""
        <sharedKey>
            <keyType>passPhrase</keyType>
            <protected>false</protected>
            <keyMaterial>{escaped_password}</keyMaterial>
        </sharedKey>"""

        return f"""<?xml version="1.0"?>
<WLANProfile xmlns="http://www.microsoft.com/networking/WLAN/profile/v1">
    <name>{escaped_ssid}</name>
    <SSIDConfig>
        <SSID>
            <hex>{ssid_hex}</hex>
            <name>{escaped_ssid}</name>
        </SSID>
    </SSIDConfig>
    <connectionType>ESS</connectionType>
    <connectionMode>manual</connectionMode>
    <MSM>
        <security>
            <authEncryption>
                <authentication>{auth}</authentication>
                <encryption>AES</encryption>
                <useOneX>false</useOneX>
            </authEncryption>{shared_key}
        </security>
    </MSM>
</WLANProfile>
"""

    def _split_key_value(self, line: str) -> tuple[str, str]:
        if ":" not in line:
            return line.strip(), ""
        key, value = line.split(":", 1)
        return key.strip(), value.strip()

    def _normalize_ping_target(self, target: str) -> str:
        cleaned = target.strip()
        if not cleaned:
            return ""
        if "://" not in cleaned:
            cleaned = f"//{cleaned}"
        parsed = urlparse(cleaned)
        host = parsed.hostname or cleaned.strip("/")
        return host.strip()

    def _interface_blocks(self, output: str) -> list[list[str]]:
        blocks: list[list[str]] = []
        current: list[str] = []
        for line in output.splitlines():
            key, _ = self._split_key_value(line.strip())
            if key.lower() == "name" and current:
                blocks.append(current)
                current = [line]
            elif line.strip():
                current.append(line)
        if current:
            blocks.append(current)
        return blocks

    def _parse_block(self, block: list[str]) -> dict[str, str]:
        data: dict[str, str] = {}
        for line in block:
            key, value = self._split_key_value(line.strip())
            normalized = key.lower()
            if normalized == "bssid":
                continue
            if normalized and value and normalized not in data:
                data[normalized] = value
        return data

    def _looks_connected(self, state: str) -> bool:
        return state.strip().lower() in {"connected", "متصل"}

    def _is_existing_profile_error(self, message: str) -> bool:
        lowered = message.lower()
        return (
            "already exists" in lowered
            or "cannot be overwritten" in lowered
            or "different user scope" in lowered
            or "group policy" in lowered
        )

    def _radio_state(self, data: dict[str, str]) -> bool | None:
        values = " ".join(data.values()).lower()
        if "hardware off" in values or "software off" in values:
            return False
        if "hardware on" in values or "software on" in values:
            return True
        return None

    def _status_message(self, state: str, radio_on: bool | None) -> str:
        if radio_on is False:
            return "Wi-Fi radio is off"
        if state:
            return f"Disconnected ({state})"
        return "Disconnected"

    def _friendly_netsh_error(self, output: str) -> str:
        text = output.strip() or "Unknown netsh error."
        lowered = text.lower()
        if "wireless autoconfig service" in lowered or "wlansvc" in lowered:
            return "WLAN AutoConfig service is not running."
        if "no wireless interface" in lowered or "wireless interface" in lowered:
            return "No Wi-Fi adapter was found or it is disabled."
        if "access is denied" in lowered or "administrator" in lowered:
            return "Windows denied access. Restarting an adapter may require administrator permission."
        if "network specified by profile" in lowered or "not available" in lowered:
            return "The requested SSID was not found nearby."
        if "parameter is incorrect" in lowered:
            return "Windows rejected the Wi-Fi profile. Check SSID and security type."
        return text
