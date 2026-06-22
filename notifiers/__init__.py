import os
import sys

from .discord import DiscordNotifier
from .line import LineNotifier
from .slack import SlackNotifier


NOTIFIER_CLASSES = {
    "slack": SlackNotifier,
    "discord": DiscordNotifier,
    "line": LineNotifier,
}


def get_notifiers(targets_text=None):
    targets_text = targets_text or os.environ.get("NOTIFY_TARGETS") or "slack"
    notifiers = []
    seen = set()

    for raw_target in targets_text.split(","):
        target = raw_target.strip().lower()
        if not target or target in seen:
            continue
        seen.add(target)

        notifier_class = NOTIFIER_CLASSES.get(target)
        if notifier_class is None:
            print(f"[warn] 未対応の通知先をスキップします: {target}", file=sys.stderr)
            continue
        notifiers.append(notifier_class())

    return notifiers
