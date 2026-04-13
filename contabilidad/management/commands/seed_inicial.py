"""
Comando para inicializar el plan de cuentas contables básico
y la configuración inicial de la empresa.

Uso: python manage.py seed_inicial
"""
from django.core.management.base import BaseCommand
from contabilidad.models import CuentaContable, CentroCosto, ConfiguracionEmpresa


CUENTAS_BASICAS = [
    # Activos
    ('1.1.01', 'Caja', 'activo'),
    ('1.1.02', 'Banco Cuenta Corriente', 'activo'),
    ('1.1.03', 'Cuentas por Cobrar Clientes', 'activo'),
    ('1.1.04', 'IVA Crédito Fiscal', 'activo'),
    ('1.2.01', 'Activo Fijo / Maquinaria', 'activo'),
    ('1.2.02', 'Vehículos', 'activo'),
    # Pasivos
    ('2.1.01', 'Cuentas por Pagar Proveedores', 'pasivo'),
    ('2.1.02', 'IVA Débito Fiscal', 'pasivo'),
    ('2.1.03', 'Remuneraciones por Pagar', 'pasivo'),
    ('2.1.04', 'Préstamos Bancarios', 'pasivo'),
    ('2.1.05', 'Impuestos por Pagar', 'pasivo'),
    # Patrimonio
    ('3.1.01', 'Capital', 'patrimonio'),
    ('3.1.02', 'Utilidad del Ejercicio', 'patrimonio'),
    # Ingresos
    ('4.1.01', 'Ventas Boletas', 'ingreso'),
    ('4.1.02', 'Ventas Facturas', 'ingreso'),
    ('4.1.03', 'Otros Ingresos', 'ingreso'),
    # Costos
    ('5.1.01', 'Costo de Ventas / Compras', 'costo'),
    # Gastos
    ('6.1.01', 'Remuneraciones y Sueldos', 'gasto'),
    ('6.1.02', 'Arriendo Local', 'gasto'),
    ('6.1.03', 'Servicios Básicos (Luz, Agua, Internet)', 'gasto'),
    ('6.1.04', 'Transporte y Logística', 'gasto'),
    ('6.1.05', 'Marketing y Publicidad', 'gasto'),
    ('6.1.06', 'Gastos Financieros (Comisiones, Intereses)', 'gasto'),
    ('6.1.07', 'Impuestos y Patentes', 'gasto'),
    ('6.1.08', 'Gastos Varios', 'gasto'),
]

CENTROS_COSTO = [
    'Administración',
    'Ventas',
    'Operaciones',
    'Finanzas',
]


class Command(BaseCommand):
    help = 'Carga plan de cuentas y configuración inicial'

    def handle(self, *args, **options):
        created_cuentas = 0
        for codigo, nombre, tipo in CUENTAS_BASICAS:
            _, created = CuentaContable.objects.get_or_create(
                codigo=codigo,
                defaults={'nombre': nombre, 'tipo': tipo}
            )
            if created:
                created_cuentas += 1

        created_cc = 0
        for nombre in CENTROS_COSTO:
            _, created = CentroCosto.objects.get_or_create(nombre=nombre)
            if created:
                created_cc += 1

        config = ConfiguracionEmpresa.get()

        self.stdout.write(self.style.SUCCESS(
            f'✅ {created_cuentas} cuentas contables creadas\n'
            f'✅ {created_cc} centros de costo creados\n'
            f'✅ Configuración de empresa lista\n\n'
            f'👉 Accede a /api/configuracion para configurar tu empresa'
        ))
