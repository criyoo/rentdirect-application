import time
import logging

from django.conf import settings
from django.core.management.base import BaseCommand

from core.payment_queue import enqueue_subscription_renewals

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Periodically charge due recurring subscription renewals."

    def add_arguments(self, parser):
        parser.add_argument(
            "--interval",
            type=int,
            default=getattr(settings, "SUBSCRIPTION_RENEWAL_WATCH_INTERVAL_SECONDS", 3600),
            help="Seconds to wait between renewal checks.",
        )

    def handle(self, *args, **options):
        interval = max(int(options["interval"]), 60)
        self.stdout.write(self.style.SUCCESS(f"Watching recurring subscription renewals every {interval} seconds."))
        while True:
            try:
                enqueue_subscription_renewals(source="watch_subscription_renewals")
            except Exception:
                logger.exception("Subscription renewal queue iteration failed.")
            time.sleep(interval)
