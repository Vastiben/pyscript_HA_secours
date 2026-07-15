from datetime import datetime

TELEGRAM_CHAT_ID = 7332342681
CHECK_CRON = "cron(* 18 * * *)"

_test_count = 0


def _send_telegram(message):
    service.call(
        "telegram_bot",
        "send_message",
        target=[TELEGRAM_CHAT_ID],
        message=message,
    )


@time_trigger(CHECK_CRON)
def telegram_test():
    global _test_count
    task.unique("telegram_test")

    _test_count += 1
    now = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    msg = (
        f"🧪 Test Telegram #{_test_count}\n"
        f"Heure : {now}\n"
        f"Statut : OK"
    )
    log.info(f"telegram_test: envoi message #{_test_count}")
    _send_telegram(msg)
    log.info("telegram_test: message envoyé avec succès")


@service
def telegram_test_now():
    global _test_count
    _test_count += 1
    now = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    msg = (
        f"🧪 Test Telegram manuel #{_test_count}\n"
        f"Heure : {now}\n"
        f"Statut : OK"
    )
    log.info(f"telegram_test_now: envoi manuel #{_test_count}")
    _send_telegram(msg)
    log.info("telegram_test_now: message envoyé avec succès")
