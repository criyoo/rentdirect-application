import json
import logging
import time
from typing import Any

from django.conf import settings
from django.core.management import call_command
from django.utils import timezone


logger = logging.getLogger(__name__)

TASK_FLUTTERWAVE_WEBHOOK = "flutterwave_webhook"
TASK_PROCESS_BOOKING_PAYOUTS = "process_booking_payouts"
TASK_PROCESS_READY_PAYOUTS = "process_ready_payouts"
TASK_PROCESS_SUBSCRIPTION_RENEWALS = "process_subscription_renewals"

SUPPORTED_PAYMENT_TASKS = {
    TASK_FLUTTERWAVE_WEBHOOK,
    TASK_PROCESS_BOOKING_PAYOUTS,
    TASK_PROCESS_READY_PAYOUTS,
    TASK_PROCESS_SUBSCRIPTION_RENEWALS,
}


class PaymentQueueError(Exception):
    pass


def payment_queue_backend() -> str:
    return str(getattr(settings, "PAYMENT_QUEUE_BACKEND", "sync") or "sync").strip().lower()


def payment_task_message(task: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    if task not in SUPPORTED_PAYMENT_TASKS:
        raise PaymentQueueError(f"Unsupported payment queue task: {task}")
    return {
        "task": task,
        "payload": payload or {},
        "enqueued_at": timezone.now().isoformat(),
    }


def enqueue_payment_task(task: str, payload: dict[str, Any] | None = None):
    message = payment_task_message(task, payload)
    backend = payment_queue_backend()
    if backend in {"sync", "inline"}:
        return execute_payment_task(message["task"], message["payload"])
    if backend == "rq":
        enqueue_rq_message(message)
        return None
    if backend == "sqs":
        enqueue_sqs_message(message)
        return None
    if backend in {"disabled", "none"}:
        logger.warning("Payment queue task %s dropped because PAYMENT_QUEUE_BACKEND=%s", task, backend)
        return None
    raise PaymentQueueError(f"Unsupported PAYMENT_QUEUE_BACKEND: {backend}")


def enqueue_flutterwave_webhook(body: dict[str, Any]):
    return enqueue_payment_task(TASK_FLUTTERWAVE_WEBHOOK, {"body": body})


def enqueue_booking_payout_check(booking_id) -> None:
    enqueue_payment_task(TASK_PROCESS_BOOKING_PAYOUTS, {"booking_id": str(booking_id)})


def enqueue_ready_payouts(*, source: str = "manual") -> None:
    enqueue_payment_task(TASK_PROCESS_READY_PAYOUTS, {"source": source})


def enqueue_subscription_renewals(*, source: str = "manual") -> None:
    enqueue_payment_task(TASK_PROCESS_SUBSCRIPTION_RENEWALS, {"source": source})


def redis_connection():
    redis_url = str(getattr(settings, "PAYMENT_QUEUE_REDIS_URL", "") or "").strip()
    if not redis_url:
        raise PaymentQueueError("PAYMENT_QUEUE_REDIS_URL is required for the RQ payment queue backend.")

    from redis import Redis

    return Redis.from_url(redis_url)


def enqueue_rq_message(message: dict[str, Any]) -> None:
    from rq import Queue

    queue = Queue(str(getattr(settings, "PAYMENT_QUEUE_NAME", "rentdirect-payments")), connection=redis_connection())
    queue.enqueue(
        execute_payment_task,
        message["task"],
        message["payload"],
        job_timeout=int(getattr(settings, "PAYMENT_QUEUE_JOB_TIMEOUT_SECONDS", 300)),
        result_ttl=int(getattr(settings, "PAYMENT_QUEUE_RESULT_TTL_SECONDS", 3600)),
        failure_ttl=int(getattr(settings, "PAYMENT_QUEUE_FAILURE_TTL_SECONDS", 86400)),
    )


def run_rq_worker(*, burst: bool = False) -> None:
    from rq import Queue, Worker

    connection = redis_connection()
    queue = Queue(str(getattr(settings, "PAYMENT_QUEUE_NAME", "rentdirect-payments")), connection=connection)
    worker = Worker([queue], connection=connection)
    worker.work(
        burst=burst,
        logging_level=logging.getLevelName(logger.getEffectiveLevel()),
    )


def sqs_client():
    import boto3

    kwargs = {}
    region_name = str(getattr(settings, "PAYMENT_QUEUE_AWS_REGION", "") or "").strip()
    endpoint_url = str(getattr(settings, "PAYMENT_QUEUE_SQS_ENDPOINT_URL", "") or "").strip()
    if region_name:
        kwargs["region_name"] = region_name
    if endpoint_url:
        kwargs["endpoint_url"] = endpoint_url
    return boto3.client("sqs", **kwargs)


def payment_queue_url() -> str:
    queue_url = str(getattr(settings, "PAYMENT_QUEUE_URL", "") or "").strip()
    if not queue_url:
        raise PaymentQueueError("PAYMENT_QUEUE_URL is required for the SQS payment queue backend.")
    return queue_url


def enqueue_sqs_message(message: dict[str, Any]) -> None:
    sqs_client().send_message(
        QueueUrl=payment_queue_url(),
        MessageBody=json.dumps(message, separators=(",", ":"), default=str),
        MessageAttributes={
            "task": {
                "DataType": "String",
                "StringValue": message["task"],
            }
        },
    )


def run_sqs_worker(*, once: bool = False, max_messages: int | None = None) -> None:
    client = sqs_client()
    queue_url = payment_queue_url()
    wait_seconds = max(min(int(getattr(settings, "PAYMENT_QUEUE_WORKER_WAIT_SECONDS", 20)), 20), 0)
    batch_size = max(min(int(getattr(settings, "PAYMENT_QUEUE_WORKER_MAX_MESSAGES", 10)), 10), 1)
    visibility_timeout = max(int(getattr(settings, "PAYMENT_QUEUE_VISIBILITY_TIMEOUT_SECONDS", 300)), 1)
    processed = 0

    while True:
        response = client.receive_message(
            QueueUrl=queue_url,
            MaxNumberOfMessages=batch_size,
            WaitTimeSeconds=wait_seconds,
            VisibilityTimeout=visibility_timeout,
            MessageAttributeNames=["All"],
            AttributeNames=["ApproximateReceiveCount"],
        )
        messages = response.get("Messages", [])
        if not messages and once:
            return

        for raw_message in messages:
            receipt_handle = raw_message["ReceiptHandle"]
            try:
                message = json.loads(raw_message.get("Body") or "{}")
                execute_payment_task(message["task"], message.get("payload") or {})
            except Exception:
                logger.exception("Payment queue SQS message failed and will be retried.")
            else:
                client.delete_message(QueueUrl=queue_url, ReceiptHandle=receipt_handle)
                processed += 1
                if max_messages is not None and processed >= max_messages:
                    return

        if once:
            return


def execute_payment_task(task: str, payload: dict[str, Any] | None = None):
    payload = payload or {}
    if task == TASK_FLUTTERWAVE_WEBHOOK:
        from core.views import process_flutterwave_webhook_event

        result = process_flutterwave_webhook_event(payload.get("body") or payload)
        if int(result.get("status_code", 200)) >= 500:
            raise PaymentQueueError(f"Flutterwave webhook processing failed: {result.get('response')}")
        return result

    if task == TASK_PROCESS_BOOKING_PAYOUTS:
        from core.models import Booking
        from core.views import trigger_booking_payouts_if_ready

        booking_id = str(payload.get("booking_id") or "").strip()
        if not booking_id:
            raise PaymentQueueError("process_booking_payouts requires booking_id")
        booking = (
            Booking.objects.select_related("tenant", "listing", "listing__landlord")
            .filter(pk=booking_id)
            .first()
        )
        if not booking:
            return {"status": "not_found", "booking_id": booking_id}
        trigger_booking_payouts_if_ready(booking)
        return {"status": "ok", "booking_id": booking_id}

    if task == TASK_PROCESS_READY_PAYOUTS:
        call_command("process_ready_payouts")
        return {"status": "ok"}

    if task == TASK_PROCESS_SUBSCRIPTION_RENEWALS:
        from core.views import process_due_subscription_renewals

        return {"status": "ok", "result": process_due_subscription_renewals()}

    raise PaymentQueueError(f"Unsupported payment queue task: {task}")


def watch_scheduled_payment_tasks(*, once: bool = False) -> None:
    payout_interval = max(int(getattr(settings, "PAYMENT_QUEUE_READY_PAYOUT_INTERVAL_SECONDS", 900)), 60)
    renewal_interval = max(int(getattr(settings, "PAYMENT_QUEUE_SUBSCRIPTION_RENEWAL_INTERVAL_SECONDS", 3600)), 60)
    last_payout_run = 0.0
    last_renewal_run = 0.0

    while True:
        now = time.monotonic()
        if now - last_payout_run >= payout_interval:
            try:
                enqueue_ready_payouts(source="payment_queue_scheduler")
            except Exception:
                logger.exception("Failed to enqueue scheduled ready-payout task.")
            last_payout_run = now
        if now - last_renewal_run >= renewal_interval:
            try:
                enqueue_subscription_renewals(source="payment_queue_scheduler")
            except Exception:
                logger.exception("Failed to enqueue scheduled subscription-renewal task.")
            last_renewal_run = now
        if once:
            return
        time.sleep(min(30, payout_interval, renewal_interval))
