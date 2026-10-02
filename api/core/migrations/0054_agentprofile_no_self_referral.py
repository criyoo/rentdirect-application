from django.db import migrations, models


def clear_self_referrals(apps, schema_editor):
    """Null out referred_by on rows where an agent refers itself."""
    AgentProfile = apps.get_model("core", "AgentProfile")
    AgentProfile.objects.filter(referred_by=models.F("user")).update(referred_by=None)


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0053_message_role_context"),
    ]

    operations = [
        migrations.RunPython(clear_self_referrals, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="agentprofile",
            constraint=models.CheckConstraint(
                condition=models.Q(referred_by__isnull=True) | ~models.Q(referred_by=models.F("user")),
                name="core_agentprof_no_self_ref",
            ),
        ),
    ]
