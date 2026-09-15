from django.core.management.base import BaseCommand

from core.views import reconcile_pending_customer_payments


class Command(BaseCommand):
    help = "Verify pending Flutterwave collections by transaction reference and update local payment records."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=100)

    def handle(self, *args, **options):
        result = reconcile_pending_customer_payments(limit=max(options["limit"], 1))
        self.stdout.write(
            self.style.SUCCESS(
                "Checked {checked} pending payment(s); completed {completed}; still pending {pending}; failed {failed}.".format(
                    **result
                )
            )
        )
