from django.core.management.base import BaseCommand

from core.payment_queue import payment_queue_backend, run_rq_worker, run_sqs_worker


class Command(BaseCommand):
    help = "Run the payment queue worker for the configured backend."

    def add_arguments(self, parser):
        parser.add_argument("--burst", action="store_true", help="Process currently available jobs and exit.")
        parser.add_argument("--max-messages", type=int, default=None, help="Maximum SQS messages to process before exiting.")

    def handle(self, *args, **options):
        backend = payment_queue_backend()
        if backend == "rq":
            self.stdout.write(self.style.SUCCESS("Starting RQ payment queue worker."))
            run_rq_worker(burst=bool(options["burst"]))
            return
        if backend == "sqs":
            self.stdout.write(self.style.SUCCESS("Starting SQS payment queue worker."))
            run_sqs_worker(
                once=bool(options["burst"]),
                max_messages=options["max_messages"],
            )
            return

        self.stdout.write(f"PAYMENT_QUEUE_BACKEND={backend}; no worker process is required.")
