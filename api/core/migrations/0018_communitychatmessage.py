import uuid

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0017_appuser_tenant_verification_profile"),
    ]

    operations = [
        migrations.CreateModel(
            name="CommunityChatMessage",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("content", models.TextField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "sender",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="community_chat_messages",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
        ),
        migrations.AddIndex(
            model_name="communitychatmessage",
            index=models.Index(fields=["-created_at"], name="core_commchat_ct_idx"),
        ),
        migrations.AddIndex(
            model_name="communitychatmessage",
            index=models.Index(fields=["sender", "-created_at"], name="core_commchat_sender_ct_idx"),
        ),
    ]
