from django.utils import timezone

from .models import AppUser, SubscriptionPayment


FREE_PLAN_CODE = SubscriptionPayment.PlanCode.BRONZE
PLAN_RANK = {
    SubscriptionPayment.PlanCode.BRONZE: 0,
    SubscriptionPayment.PlanCode.SILVER: 1,
    SubscriptionPayment.PlanCode.GOLD: 2,
    SubscriptionPayment.PlanCode.PLATINUM: 3,
}

SUPPORT_RESPONSE_TIMES = {
    AppUser.Role.TENANT: {
        SubscriptionPayment.PlanCode.BRONZE: "up to 7 days",
        SubscriptionPayment.PlanCode.SILVER: "up to 3 days",
        SubscriptionPayment.PlanCode.GOLD: "up to 24 hours",
        SubscriptionPayment.PlanCode.PLATINUM: "up to 4 hours",
    },
    AppUser.Role.LANDLORD: {
        SubscriptionPayment.PlanCode.BRONZE: "up to 7 days",
        SubscriptionPayment.PlanCode.SILVER: "up to 5 days",
        SubscriptionPayment.PlanCode.GOLD: "up to 3 days",
        SubscriptionPayment.PlanCode.PLATINUM: "up to 24 hours",
    },
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


def support_response_time_for(user):
    plan_code = active_plan_code_for(user)
    role_response_times = SUPPORT_RESPONSE_TIMES.get(user.role, SUPPORT_RESPONSE_TIMES[AppUser.Role.TENANT])
    return role_response_times.get(plan_code, role_response_times[FREE_PLAN_CODE])


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
