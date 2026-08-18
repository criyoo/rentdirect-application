from rest_framework.permissions import BasePermission


FROZEN_ACCOUNT_MESSAGE = "Your account is frozen. Unfreeze it to access RentDirect services."


def is_frozen_account(user) -> bool:
    return bool(
        getattr(user, "is_authenticated", False)
        and getattr(user, "role", None) in {"tenant", "landlord"}
        and getattr(user, "is_account_frozen", False)
    )


class AllowAnyUnlessFrozen(BasePermission):
    message = FROZEN_ACCOUNT_MESSAGE

    def has_permission(self, request, view):
        return not is_frozen_account(request.user)


class IsAuthenticatedUnlessFrozen(BasePermission):
    message = FROZEN_ACCOUNT_MESSAGE

    def has_permission(self, request, view):
        return bool(
            getattr(request.user, "is_authenticated", False)
            and not is_frozen_account(request.user)
        )


class IsRole(BasePermission):
    roles: set[str] = set()

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.role in self.roles
            and not is_frozen_account(request.user)
        )


class IsAdminRole(IsRole):
    roles = {"admin"}


class IsLandlordOrAdmin(IsRole):
    roles = {"landlord", "admin"}


class IsTenant(IsRole):
    roles = {"tenant"}
