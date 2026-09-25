from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0039_listing_ai_search_fields"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="listing",
            name="postal_code",
        ),
    ]
