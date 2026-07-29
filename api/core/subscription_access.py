from django.utils import timezone

from .models import SubscriptionPayment


FREE_PLAN_CODE = SubscriptionPayment.PlanCode.BRONZE
PLAN_RANK = {
    SubscriptionPayment.PlanCode.BRONZE: 0,
    SubscriptionPayment.PlanCode.SILVER: 1,
    SubscriptionPayment.PlanCode.GOLD: 2,
    SubscriptionPayment.PlanCode.PLATINUM: 3,
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


def user_has_plan_access(user, required_plan):
    return PLAN_RANK.get(active_plan_code_for(user), 0) >= PLAN_RANK[required_plan]


def user_has_silver_access(user):
    return user_has_plan_access(user, SubscriptionPayment.PlanCode.SILVER)


def user_has_gold_access(user):
    return user_has_plan_access(user, SubscriptionPayment.PlanCode.GOLD)


def user_has_platinum_access(user):
    return user_has_plan_access(user, SubscriptionPayment.PlanCode.PLATINUM)


def user_has_active_community_chat_subscription(user):
    return user_has_gold_access(user)
