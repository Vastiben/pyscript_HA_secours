import subprocess
import re
from datetime import datetime

TARGET_NAME = "ha-master"
TARGET_IP = "172.27.66.1"
CHECK_CRON = "cron(*/1 * * * *)"
FAIL_THRESHOLD = 10
HANDSHAKE_MAX = 180          # secondes — au-delà, le tunnel est considéré mort
TWILIO_TARGET = "+41792763781"
TELEGRAM_CHAT_ID = 7332342681

fail_count = 0
link_down = False


def _get_wireguard_stats():
    """
    Retourne (handshake_age_seconds, rx_bytes, tx_bytes) depuis les logs WireGuard.
    Retourne (None, 0, 0) si parsing impossible.
    """
    token = os.environ.get("SUPERVISOR_TOKEN", "")
    result = subprocess.run(
        ["curl", "-sf", "-H", f"Authorization: Bearer {token}",
         "http://supervisor/addons/a0d7b954_wireguard/logs"],
        capture_output=True, text=True, timeout=10
    )
    lines = result.stdout.splitlines()

    handshake_seconds = None
    rx_bytes = 0
    tx_bytes = 0

    for line in reversed(lines):
        # Handshake: "latest handshake: 1 minute, 7 seconds ago" ou "X seconds ago"
        if handshake_seconds is None and "latest handshake" in line:
            minutes = 0
            seconds = 0
            m = re.search(r"(\d+) minute", line)
            if m:
                minutes = int(m.group(1))
            s = re.search(r"(\d+) second", line)
            if s:
                seconds = int(s.group(1))
            handshake_seconds = minutes * 60 + seconds

        # Transfer: "transfer: 425.24 MiB received, 884.07 MiB sent"
        if rx_bytes == 0 and "transfer:" in line:
            m = re.search(r"transfer:\s*([\d.]+)\s*(\w+)\s*received,\s*([\d.]+)\s*(\w+)\s*sent", line)
            if m:
                rx_val, rx_unit = float(m.group(1)), m.group(2).upper()
                tx_val, tx_unit = float(m.group(3)), m.group(4).upper()
                def to_bytes(val, unit):
                    factors = {"B": 1, "KIB": 1024, "MIB": 1024**2, "GIB": 1024**3}
                    return int(val * factors.get(unit, 1))
                rx_bytes = to_bytes(rx_val, rx_unit)
                tx_bytes = to_bytes(tx_val, tx_unit)

        if handshake_seconds is not None and rx_bytes > 0:
            break

    return handshake_seconds, rx_bytes, tx_bytes


def _send_telegram(message):
    service.call(
        "telegram_bot",
        "send_message",
        target=[TELEGRAM_CHAT_ID],
        message=message
    )


def _notify_down(message):
    service.call(
        "persistent_notification",
        "create",
        title="🔌 WireGuard déconnecté",
        message=message,
        notification_id="wireguard_ha_slave_down"
    )
    service.call(
        "notify",
        "notifier_twilio",
        message=message,
        target=[TWILIO_TARGET]
    )
    _send_telegram(f"🔌 {message}")


def _notify_up(message):
    _send_telegram(f"✅ {message}")


def _clear_down_notification():
    service.call(
        "persistent_notification",
        "dismiss",
        notification_id="wireguard_ha_slave_down"
    )


def _set_status(status, details="", handshake_age=None, rx_bytes=0, tx_bytes=0):
    state.set(
        "sensor.wireguard_ha_slave_status",
        value=status,
        new_attributes={
            "friendly_name": "WireGuard ha-slave",
            "target_ip": TARGET_IP,
            "fail_count": fail_count,
            "last_check": datetime.now().isoformat(),
            "handshake_age_seconds": handshake_age,
            "rx_bytes": rx_bytes,
            "tx_bytes": tx_bytes,
            "details": details,
        }
    )


def _run_check(source="cron"):
    global fail_count, link_down

    task.unique("wireguard_ha_slave_check")
    log.info(f"▶ wireguard_ha_slave_check démarré ({source}) | critères: handshake<{HANDSHAKE_MAX}s + transfer rx/tx>0")

    handshake_age, rx_bytes, tx_bytes = _get_wireguard_stats()

    # Évaluation de l'état
    handshake_ok = handshake_age is not None and handshake_age < HANDSHAKE_MAX
    traffic_ok = rx_bytes > 0 and tx_bytes > 0

    details = (
        f"handshake={handshake_age}s (max={HANDSHAKE_MAX}s) | "
        f"rx={rx_bytes} B | tx={tx_bytes} B"
    )
    log.debug(f"  check handshake+transfer | {details} | handshake_ok={handshake_ok} | traffic_ok={traffic_ok}")

    ok = handshake_ok and traffic_ok

    if ok:
        if link_down:
            msg = (
                f"Lien WireGuard rétabli vers {TARGET_NAME} ({TARGET_IP}).\n"
                f"Heure : {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}\n"
                f"Détail : {details}"
            )
            log.warning(f"✅ {msg}")
            _clear_down_notification()
            _notify_up(msg)

        fail_count = 0
        link_down = False
        _set_status("up", details, handshake_age, rx_bytes, tx_bytes)
        log.info(f"✅ wireguard_ha_slave_check terminé - lien OK | {details}")
        return

    fail_count += 1
    _set_status("down", details, handshake_age, rx_bytes, tx_bytes)
    log.warning(
        f"⚠ wireguard_ha_slave_check - échec {fail_count}/{FAIL_THRESHOLD} | "
        f"handshake_ok={handshake_ok} | traffic_ok={traffic_ok} | {details}"
    )

    if fail_count >= FAIL_THRESHOLD and not link_down:
        msg = (
            f"Lien WireGuard indisponible vers {TARGET_NAME} ({TARGET_IP}).\n"
            f"Échecs consécutifs : {fail_count}\n"
            f"Heure : {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}\n"
            f"Détail : {details}"
        )
        log.error(f"❌ {msg}")
        _notify_down(msg)
        link_down = True

    log.info("wireguard_ha_slave_check terminé")


@time_trigger(CHECK_CRON)
def wireguard_ha_slave_check():
    _run_check("cron")


@service
def wireguard_ha_slave_check_now():
    _run_check("manuel")
