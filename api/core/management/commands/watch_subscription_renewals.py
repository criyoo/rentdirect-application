import time

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand


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
            call_command("process_subscription_renewals")
            time.sleep(interval)
