from rest_framework.permissions import BasePermission


class IsRole(BasePermission):
    roles: set[str] = set()

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.role in self.roles)


class IsAdminRole(IsRole):
    roles = {"admin"}


class IsLandlordOrAdmin(IsRole):
    roles = {"landlord", "admin"}


class IsTenant(IsRole):
    roles = {"tenant"}
