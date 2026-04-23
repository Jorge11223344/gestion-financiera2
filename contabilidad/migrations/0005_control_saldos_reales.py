from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('contabilidad', '0004_rename_mov_fecha_cuenta_idx_contabilida_fecha_0d7ee6_idx_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='ControlSaldoReal',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('fecha', models.DateField(unique=True)),
                ('pendiente_efectivo_clp', models.DecimalField(decimal_places=2, default=0, max_digits=18)),
                ('notas', models.TextField(blank=True)),
                ('creado_en', models.DateTimeField(auto_now_add=True)),
                ('actualizado_en', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'Control de Saldo Real',
                'verbose_name_plural': 'Controles de Saldos Reales',
                'ordering': ['-fecha', '-creado_en'],
            },
        ),
        migrations.CreateModel(
            name='ControlSaldoRealDetalle',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('saldo_real', models.DecimalField(decimal_places=4, default=0, max_digits=18)),
                ('control', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='detalles', to='contabilidad.controlsaldoreal')),
                ('cuenta_financiera', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='controles_saldo_real', to='contabilidad.cuentafinanciera')),
            ],
            options={
                'verbose_name': 'Detalle Control Saldo Real',
                'verbose_name_plural': 'Detalles Control Saldo Real',
                'ordering': ['cuenta_financiera__institucion', 'cuenta_financiera__nombre'],
                'unique_together': {('control', 'cuenta_financiera')},
            },
        ),
    ]
