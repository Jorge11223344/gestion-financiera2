"""
Comando de gestión para poblar datos iniciales.
Crea:
  - Plan de cuentas contables básico
  - Cuentas financieras de ejemplo (Global66 CLP, Global66 USD, Banco de Chile)
  - Configuración de empresa de ejemplo

Uso:
    python manage.py seed_inicial
    python manage.py seed_inicial --reset   # borra y recrea todo
"""
from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = 'Carga datos iniciales: plan de cuentas, cuentas financieras y configuración'

    def add_arguments(self, parser):
        parser.add_argument(
            '--reset',
            action='store_true',
            help='Elimina datos existentes antes de cargar',
        )

    def handle(self, *args, **options):
        from contabilidad.models import (
            CuentaContable, CuentaFinanciera, ConfiguracionEmpresa
        )

        if options['reset']:
            CuentaContable.objects.all().delete()
            CuentaFinanciera.objects.all().delete()
            self.stdout.write('🗑️  Datos existentes eliminados')

        # ── Plan de Cuentas Contables ─────────────────────────────────
        cuentas = [
            # Activos
            ('1.1.01', 'Caja',                           'activo'),
            ('1.1.02', 'Banco Cuenta Corriente',          'activo'),
            ('1.1.03', 'Banco Cuenta Vista / RUT',        'activo'),
            ('1.1.04', 'Billetera Digital CLP',           'activo'),
            ('1.1.05', 'Billetera Digital USD',           'activo'),
            ('1.1.10', 'Clientes por Cobrar',             'activo'),
            ('1.1.20', 'IVA Crédito Fiscal',              'activo'),
            ('1.1.30', 'Inventario / Mercadería',         'activo'),
            ('1.1.40', 'Anticipo a Proveedores',          'activo'),
            ('1.2.01', 'Activo Fijo - Equipos',           'activo'),
            ('1.2.02', 'Activo Fijo - Vehículos',         'activo'),
            # Pasivos
            ('2.1.01', 'Proveedores por Pagar',           'pasivo'),
            ('2.1.02', 'IVA Débito Fiscal',               'pasivo'),
            ('2.1.03', 'Remuneraciones por Pagar',        'pasivo'),
            ('2.1.04', 'Impuestos por Pagar',             'pasivo'),
            ('2.1.10', 'Préstamos Bancarios CP',          'pasivo'),
            ('2.2.01', 'Préstamos Bancarios LP',          'pasivo'),
            # Patrimonio
            ('3.1.01', 'Capital',                         'patrimonio'),
            ('3.1.02', 'Aportes de Socios',               'patrimonio'),
            ('3.1.03', 'Utilidades Retenidas',            'patrimonio'),
            # Ingresos
            ('4.1.01', 'Ventas Nacionales',               'ingreso'),
            ('4.1.02', 'Ventas con Boleta',               'ingreso'),
            ('4.1.03', 'Ventas con Factura',              'ingreso'),
            ('4.2.01', 'Intereses Ganados',               'ingreso'),
            ('4.2.02', 'Otros Ingresos',                  'ingreso'),
            # Costos
            ('5.1.01', 'Costo de Mercadería Vendida',     'costo'),
            ('5.1.02', 'Importaciones - Costo Producto',  'costo'),
            ('5.1.03', 'Gastos de Internación',           'costo'),
            # Gastos
            ('6.1.01', 'Remuneraciones',                  'gasto'),
            ('6.1.02', 'Honorarios',                      'gasto'),
            ('6.2.01', 'Arriendo',                        'gasto'),
            ('6.2.02', 'Servicios Básicos',               'gasto'),
            ('6.2.03', 'Marketing y Publicidad',          'gasto'),
            ('6.3.01', 'Logística y Transporte',          'gasto'),
            ('6.3.02', 'Flete Internacional',             'gasto'),
            ('6.3.03', 'Gastos de Aduana',                'gasto'),
            ('6.4.01', 'IVA (gasto cuando no recuperable)', 'gasto'),
            ('6.4.02', 'Impuesto de Primera Categoría',   'gasto'),
            ('6.4.03', 'Patente Municipal',               'gasto'),
            ('6.5.01', 'Comisiones Bancarias',            'gasto'),
            ('6.5.02', 'Intereses Préstamos',             'gasto'),
            ('6.5.03', 'Diferencia de Cambio',            'gasto'),
            ('6.6.01', 'Otros Gastos Operacionales',      'gasto'),
        ]

        creadas = 0
        for codigo, nombre, tipo in cuentas:
            _, created = CuentaContable.objects.get_or_create(
                codigo=codigo,
                defaults={'nombre': nombre, 'tipo': tipo}
            )
            if created:
                creadas += 1

        self.stdout.write(f'✅ Plan de cuentas: {creadas} cuentas creadas')

        # ── Cuentas Financieras de Ejemplo ────────────────────────────
        cuentas_financieras = [
            {
                'nombre': 'Global66 CLP',
                'institucion': 'Global66',
                'tipo_cuenta': 'billetera_digital',
                'moneda': 'CLP',
                'notas': 'Cuenta en pesos chilenos en Global66. '
                         'Exportar desde: Cuenta → Movimientos → Exportar (.xls)',
            },
            {
                'nombre': 'Global66 USD',
                'institucion': 'Global66',
                'tipo_cuenta': 'billetera_digital',
                'moneda': 'USD',
                'notas': 'Cuenta en dólares en Global66. '
                         'Exportar desde: Cuenta → Movimientos → Exportar (.xls)',
            },
            {
                'nombre': 'Banco de Chile CC',
                'institucion': 'Banco de Chile',
                'tipo_cuenta': 'cuenta_corriente',
                'moneda': 'CLP',
                'notas': 'Cuenta corriente Banco de Chile. '
                         'Exportar desde: Empresas → Cuenta Corriente → Cartola → Exportar Excel',
            },
        ]

        cf_creadas = 0
        for datos in cuentas_financieras:
            _, created = CuentaFinanciera.objects.get_or_create(
                nombre=datos['nombre'],
                institucion=datos['institucion'],
                defaults=datos,
            )
            if created:
                cf_creadas += 1

        self.stdout.write(f'✅ Cuentas financieras: {cf_creadas} creadas')

        # ── Configuración de Empresa ──────────────────────────────────
        config = ConfiguracionEmpresa.get()
        if config.nombre == 'Mi Empresa':
            config.nombre = 'Mi Empresa SpA'
            config.moneda = 'CLP'
            config.save()
            self.stdout.write('✅ Configuración de empresa actualizada')

        self.stdout.write(self.style.SUCCESS(
            '\n🎉 Datos iniciales cargados correctamente.\n'
            '   Próximos pasos:\n'
            '   1. Ve a ⚙️ Configuración y actualiza los datos de tu empresa\n'
            '   2. Ve a 🏦 Cuentas y ajusta los saldos iniciales de cada cuenta\n'
            '   3. Ve a 🏦 Importar Cartola y sube tu primera cartola bancaria\n'
        ))