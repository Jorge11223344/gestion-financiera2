from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('contabilidad', '0002_multimoneda'),
    ]

    operations = [
        migrations.AddField(
            model_name='movimientodiario',
            name='tc_pendiente',
            field=models.BooleanField(
                default=False,
                help_text='True cuando el movimiento es en moneda extranjera y no trajo '
                          'tipo de cambio en la cartola. Requiere ingreso manual del TC '
                          'para que el monto en CLP sea correcto.'
            ),
        ),
    ]
