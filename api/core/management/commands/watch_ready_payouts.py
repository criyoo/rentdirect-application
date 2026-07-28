import logging
import time

from django.conf import settings
from django.core.management.base import BaseCommand

from core.payment_queue import enqueue_ready_payouts

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Run the rent-payout release check on a fixed interval."

    def handle(self, *args, **options):
        interval_seconds = max(int(getattr(settings, "FLUTTERWAVE_PAYOUT_RELEASE_WATCH_INTERVAL_SECONDS", 300)), 60)
        self.stdout.write(f"Watching ready payouts every {interval_seconds} second(s).")

        while True:
            try:
                enqueue_ready_payouts(source="watch_ready_payouts")
            except Exception:
                logger.exception("Ready payout queue iteration failed.")
            time.sleep(interval_seconds)
