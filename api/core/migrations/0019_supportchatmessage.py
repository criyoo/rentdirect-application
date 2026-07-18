import uuid

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0018_communitychatmessage"),
    ]

    operations = [
        migrations.CreateModel(
            name="SupportChatMessage",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("content", models.TextField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "sender",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="support_chat_messages",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "thread_user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="support_chat_threads",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
        ),
        migrations.AddIndex(
            model_name="supportchatmessage",
            index=models.Index(fields=["thread_user", "-created_at"], name="core_supportchat_thread_ct_idx"),
        ),
        migrations.AddIndex(
            model_name="supportchatmessage",
            index=models.Index(fields=["sender", "-created_at"], name="core_supportchat_sender_ct_idx"),
        ),
    ]
