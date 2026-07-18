import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Create or update an admin user from environment variables."

    def handle(self, *args, **options):
        email = os.environ.get("DJANGO_SUPERUSER_EMAIL")
        password = os.environ.get("DJANGO_SUPERUSER_PASSWORD")
        name = os.environ.get("DJANGO_SUPERUSER_NAME", "Admin")
        if not email or not password:
            self.stdout.write("DJANGO_SUPERUSER_EMAIL/PASSWORD not set; skipping")
            return
        User = get_user_model()
        user, created = User.objects.get_or_create(
            email=email.lower(),
            defaults={"name": name, "role": "admin", "email_verified": True, "is_staff": True, "is_superuser": True},
        )
        user.name = name
        user.role = "admin"
        user.email_verified = True
        user.is_staff = True
        user.is_superuser = True
        user.set_password(password)
        user.save()
        self.stdout.write(self.style.SUCCESS(("Created" if created else "Updated") + f" admin {email}"))
