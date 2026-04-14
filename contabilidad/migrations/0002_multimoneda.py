from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ('contabilidad', '0001_initial'),
    ]

    operations = [
        # 1. CuentaFinanciera
        migrations.CreateModel(
            name='CuentaFinanciera',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('nombre', models.CharField(max_length=100)),
                ('institucion', models.CharField(max_length=100)),
                ('tipo_cuenta', models.CharField(choices=[('cuenta_corriente', 'Cuenta Corriente'), ('cuenta_vista', 'Cuenta Vista / RUT'), ('billetera_digital', 'Billetera Digital'), ('credito', 'Línea de Crédito'), ('caja', 'Caja (Efectivo)'), ('otra', 'Otra')], default='cuenta_corriente', max_length=20)),
                ('moneda', models.CharField(choices=[('CLP', 'Peso Chileno (CLP)'), ('USD', 'Dólar Americano (USD)'), ('EUR', 'Euro (EUR)')], default='CLP', max_length=5)),
                ('titular', models.CharField(blank=True, max_length=150)),
                ('numero_parcial', models.CharField(blank=True, max_length=20)),
                ('activa', models.BooleanField(default=True)),
                ('saldo_inicial', models.DecimalField(decimal_places=2, default=0, max_digits=18)),
                ('fecha_saldo_inicial', models.DateField(blank=True, null=True)),
                ('notas', models.TextField(blank=True)),
                ('creado_en', models.DateTimeField(auto_now_add=True)),
            ],
            options={'ordering': ['institucion', 'moneda', 'nombre'], 'verbose_name': 'Cuenta Financiera', 'verbose_name_plural': 'Cuentas Financieras'},
        ),

        # 2. RegistroImportacion
        migrations.CreateModel(
            name='RegistroImportacion',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('nombre_archivo', models.CharField(max_length=255)),
                ('banco_detectado', models.CharField(blank=True, max_length=100)),
                ('fecha_importacion', models.DateTimeField(auto_now_add=True)),
                ('total_filas_archivo', models.IntegerField(default=0)),
                ('total_importados', models.IntegerField(default=0)),
                ('total_duplicados', models.IntegerField(default=0)),
                ('total_errores', models.IntegerField(default=0)),
                ('estado', models.CharField(choices=[('completado', 'Completado'), ('con_errores', 'Completado con errores'), ('revertido', 'Revertido')], default='completado', max_length=20)),
                ('hash_archivo', models.CharField(max_length=64, unique=True)),
                ('advertencias', models.JSONField(blank=True, default=list)),
                ('cuenta_financiera', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='importaciones', to='contabilidad.cuentafinanciera')),
            ],
            options={'ordering': ['-fecha_importacion'], 'verbose_name': 'Importación'},
        ),

        # 3. Nuevos campos en MovimientoDiario
        migrations.AddField(
            model_name='movimientodiario',
            name='cuenta_financiera',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='movimientos', to='contabilidad.cuentafinanciera'),
        ),
        migrations.AddField(
            model_name='movimientodiario',
            name='moneda',
            field=models.CharField(choices=[('CLP', 'CLP'), ('USD', 'USD'), ('EUR', 'EUR')], default='CLP', max_length=5),
        ),
        migrations.AddField(
            model_name='movimientodiario',
            name='monto_moneda_orig',
            field=models.DecimalField(blank=True, decimal_places=4, max_digits=18, null=True),
        ),
        migrations.AddField(
            model_name='movimientodiario',
            name='tipo_cambio',
            field=models.DecimalField(blank=True, decimal_places=4, max_digits=12, null=True),
        ),
        migrations.AddField(
            model_name='movimientodiario',
            name='importacion',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='movimientos', to='contabilidad.registroimportacion'),
        ),
        migrations.AddField(
            model_name='movimientodiario',
            name='referencia_externa',
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name='movimientodiario',
            name='es_transferencia_interna',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='movimientodiario',
            name='movimiento_relacionado',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='movimientos_relacionados', to='contabilidad.movimientodiario'),
        ),
        migrations.AddField(
            model_name='movimientodiario',
            name='categoria_normalizada',
            field=models.CharField(blank=True, choices=[('venta', 'Venta / Boleta / Factura'), ('aporte_socio', 'Aporte de Socio'), ('interes_ganado', 'Interés Ganado'), ('reembolso', 'Reembolso'), ('pago_proveedor', 'Pago a Proveedor'), ('pago_importacion', 'Pago Importación'), ('gasto_logistica', 'Gasto Logístico'), ('remuneracion_norm', 'Remuneración'), ('gasto_operacional', 'Gasto Operacional'), ('comision_bancaria', 'Comisión Bancaria'), ('pago_impuesto', 'Pago Impuesto'), ('pago_prestamo_norm', 'Pago Préstamo'), ('transferencia_interna', 'Transferencia Interna'), ('conversion_divisa', 'Conversión de Divisa'), ('sin_clasificar', 'Sin Clasificar')], default='sin_clasificar', max_length=30),
        ),
        migrations.AddField(
            model_name='movimientodiario',
            name='tercero',
            field=models.CharField(blank=True, max_length=200),
        ),
        migrations.AddField(
            model_name='movimientodiario',
            name='pais_tercero',
            field=models.CharField(blank=True, max_length=5),
        ),
        migrations.AddField(
            model_name='movimientodiario',
            name='clasificacion_confianza',
            field=models.CharField(blank=True, choices=[('alta', 'Alta'), ('media', 'Media'), ('baja', 'Baja')], max_length=10),
        ),
        migrations.AddField(
            model_name='movimientodiario',
            name='clasificacion_razon',
            field=models.CharField(blank=True, max_length=250),
        ),

        # 4. Índices para rendimiento
        migrations.AddIndex(
            model_name='movimientodiario',
            index=models.Index(fields=['fecha', 'cuenta_financiera'], name='mov_fecha_cuenta_idx'),
        ),
        migrations.AddIndex(
            model_name='movimientodiario',
            index=models.Index(fields=['categoria_normalizada'], name='mov_categoria_idx'),
        ),
        migrations.AddIndex(
            model_name='movimientodiario',
            index=models.Index(fields=['es_transferencia_interna'], name='mov_interna_idx'),
        ),
    ]