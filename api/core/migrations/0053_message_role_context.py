from django.db import migrations, models


def populate_message_role_context(apps, schema_editor):
    """Backfill persisted communication persona context.

    Rules:
    - Message with a listing: sender is the listing landlord -> landlord -> tenant;
      receiver is the listing landlord -> tenant -> landlord; otherwise both sides
      keep each user's legacy/default role.
    - CommunityChatMessage.role = sender's legacy role.
    - SupportChatMessage.thread_role = thread_user's legacy role; sender_role =
      admin when the sender differs from the thread user, else thread_role.
    """
    Message = apps.get_model("core", "Message")
    CommunityChatMessage = apps.get_model("core", "CommunityChatMessage")
    SupportChatMessage = apps.get_model("core", "SupportChatMessage")

    for message in Message.objects.iterator():
        sender_role = message.sender.role
        receiver_role = message.receiver.role
        listing = message.listing
        if listing is not None:
            if message.sender_id == listing.landlord_id:
                sender_role, receiver_role = "landlord", "tenant"
            elif message.receiver_id == listing.landlord_id:
                sender_role, receiver_role = "tenant", "landlord"
        if message.sender_role != sender_role or message.receiver_role != receiver_role:
            message.sender_role = sender_role
            message.receiver_role = receiver_role
            message.save(update_fields=["sender_role", "receiver_role"])

    for chat_message in CommunityChatMessage.objects.iterator():
        role = chat_message.sender.role
        if chat_message.role != role:
            chat_message.role = role
            chat_message.save(update_fields=["role"])

    for chat_message in SupportChatMessage.objects.iterator():
        thread_role = chat_message.thread_user.role
        sender_role = (
            thread_role
            if chat_message.sender_id == chat_message.thread_user_id
            else "admin"
        )
        if (
            chat_message.thread_role != thread_role
            or chat_message.sender_role != sender_role
        ):
            chat_message.thread_role = thread_role
            chat_message.sender_role = sender_role
            chat_message.save(update_fields=["thread_role", "sender_role"])


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0052_multi_role_identities"),
    ]

    operations = [
        migrations.AddField(
            model_name="message",
            name="sender_role",
            field=models.CharField(choices=[("tenant", "Tenant"), ("landlord", "Landlord"), ("agent", "Property Inspection Officer"), ("admin", "Admin")], max_length=20, db_index=True, default="tenant"),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="message",
            name="receiver_role",
            field=models.CharField(choices=[("tenant", "Tenant"), ("landlord", "Landlord"), ("agent", "Property Inspection Officer"), ("admin", "Admin")], max_length=20, db_index=True, default="landlord"),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="communitychatmessage",
            name="role",
            field=models.CharField(choices=[("tenant", "Tenant"), ("landlord", "Landlord"), ("agent", "Property Inspection Officer"), ("admin", "Admin")], max_length=20, db_index=True, default="tenant"),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="supportchatmessage",
            name="thread_role",
            field=models.CharField(choices=[("tenant", "Tenant"), ("landlord", "Landlord"), ("agent", "Property Inspection Officer"), ("admin", "Admin")], max_length=20, db_index=True, default="tenant"),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="supportchatmessage",
            name="sender_role",
            field=models.CharField(choices=[("tenant", "Tenant"), ("landlord", "Landlord"), ("agent", "Property Inspection Officer"), ("admin", "Admin")], max_length=20, default="tenant"),
            preserve_default=False,
        ),
        migrations.RunPython(populate_message_role_context, migrations.RunPython.noop),
    ]
