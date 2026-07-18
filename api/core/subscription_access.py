from django.utils import timezone

from .models import SubscriptionPayment


FREE_PLAN_CODE = SubscriptionPayment.PlanCode.BRONZE
COMMUNITY_CHAT_PLAN_CODES = {
    SubscriptionPayment.PlanCode.GOLD,
    SubscriptionPayment.PlanCode.PLATINUM,
}


def active_subscription_for(user):
    if not getattr(user, "is_authenticated", False):
        return None
    return (
        SubscriptionPayment.objects.filter(
            user=user,
            role=user.role,
            status=SubscriptionPayment.Status.COMPLETED,
            expires_at__gte=timezone.now(),
        )
        .order_by("-payment_date", "-created_at")
        .first()
    )


def active_plan_code_for(user):
    subscription = active_subscription_for(user)
    if not subscription:
        return FREE_PLAN_CODE
    return subscription.plan_code


def user_has_bronze_access(user):
    return active_plan_code_for(user) == FREE_PLAN_CODE


def user_has_active_community_chat_subscription(user):
    return active_plan_code_for(user) in COMMUNITY_CHAT_PLAN_CODES
