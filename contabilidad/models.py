from django.db import models
from django.utils import timezone
import uuid


class CuentaContable(models.Model):
    """Plan de cuentas contables"""
    TIPOS = [
        ('activo', 'Activo'),
        ('pasivo', 'Pasivo'),
        ('patrimonio', 'Patrimonio'),
        ('ingreso', 'Ingreso'),
        ('gasto', 'Gasto'),
        ('costo', 'Costo de Venta'),
    ]
    codigo = models.CharField(max_length=20, unique=True)
    nombre = models.CharField(max_length=150)
    tipo = models.CharField(max_length=20, choices=TIPOS)
    descripcion = models.TextField(blank=True)
    activa = models.BooleanField(default=True)

    class Meta:
        ordering = ['codigo']
        verbose_name = 'Cuenta Contable'
        verbose_name_plural = 'Cuentas Contables'

    def __str__(self):
        return f"{self.codigo} - {self.nombre}"


class CentroCosto(models.Model):
    """Centro de costo / área de la empresa"""
    nombre = models.CharField(max_length=100)
    descripcion = models.TextField(blank=True)
    activo = models.BooleanField(default=True)

    def __str__(self):
        return self.nombre


class MovimientoDiario(models.Model):
    """
    Registro diario de movimientos de caja/banco.
    Boletas y facturas se ingresan agrupadas (suma total).
    """
    TIPOS = [
        ('ingreso_caja', 'Ingreso Caja'),
        ('egreso_caja', 'Egreso Caja'),
        ('ingreso_banco', 'Ingreso Banco'),
        ('egreso_banco', 'Egreso Banco'),
        ('suma_boletas', 'Suma de Boletas'),
        ('suma_facturas_emitidas', 'Suma Facturas Emitidas'),
        ('suma_facturas_recibidas', 'Suma Facturas Recibidas (Compras)'),
        ('remuneracion', 'Remuneración / Sueldos'),
        ('impuesto', 'Pago Impuesto / Contribución'),
        ('prestamo_recibido', 'Préstamo Recibido'),
        ('pago_prestamo', 'Pago Préstamo / Cuota'),
        ('inversion', 'Inversión / Activo Fijo'),
        ('otro_ingreso', 'Otro Ingreso'),
        ('otro_egreso', 'Otro Egreso'),
    ]

    MEDIOS_PAGO = [
        ('efectivo', 'Efectivo'),
        ('transferencia', 'Transferencia'),
        ('cheque', 'Cheque'),
        ('tarjeta_debito', 'Tarjeta Débito'),
        ('tarjeta_credito', 'Tarjeta Crédito'),
        ('nota_credito', 'Nota de Crédito'),
        ('otro', 'Otro'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    fecha = models.DateField(default=timezone.now)
    tipo = models.CharField(max_length=40, choices=TIPOS)
    descripcion = models.CharField(max_length=250)
    monto = models.DecimalField(max_digits=14, decimal_places=0)  # CLP sin decimales
    medio_pago = models.CharField(max_length=20, choices=MEDIOS_PAGO, default='efectivo')
    cuenta = models.ForeignKey(CuentaContable, on_delete=models.SET_NULL, null=True, blank=True)
    centro_costo = models.ForeignKey(CentroCosto, on_delete=models.SET_NULL, null=True, blank=True)

    # Campos específicos para boletas/facturas
    cantidad_documentos = models.IntegerField(null=True, blank=True, help_text="Nº de boletas o facturas agrupadas")
    rut_contraparte = models.CharField(max_length=20, blank=True, help_text="RUT cliente o proveedor")
    nombre_contraparte = models.CharField(max_length=150, blank=True)

    # IVA desglosado (para facturas)
    monto_neto = models.DecimalField(max_digits=14, decimal_places=0, null=True, blank=True)
    monto_iva = models.DecimalField(max_digits=14, decimal_places=0, null=True, blank=True)

    # Metadatos
    notas = models.TextField(blank=True)
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-fecha', '-creado_en']
        verbose_name = 'Movimiento Diario'

    def __str__(self):
        return f"{self.fecha} | {self.get_tipo_display()} | ${self.monto:,.0f}"

    @property
    def es_ingreso(self):
        ingresos = ['ingreso_caja', 'ingreso_banco', 'suma_boletas',
                    'suma_facturas_emitidas', 'prestamo_recibido', 'otro_ingreso']
        return self.tipo in ingresos

    @property
    def es_egreso(self):
        return not self.es_ingreso


class CierreDiario(models.Model):
    """
    Cierre/resumen del día. Se genera automáticamente al cerrar la jornada.
    """
    fecha = models.DateField(unique=True)
    saldo_inicial_caja = models.DecimalField(max_digits=14, decimal_places=0, default=0)
    total_ingresos = models.DecimalField(max_digits=14, decimal_places=0, default=0)
    total_egresos = models.DecimalField(max_digits=14, decimal_places=0, default=0)
    saldo_final_caja = models.DecimalField(max_digits=14, decimal_places=0, default=0)
    notas = models.TextField(blank=True)
    cerrado = models.BooleanField(default=False)
    cerrado_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-fecha']

    def __str__(self):
        return f"Cierre {self.fecha}"

    @property
    def resultado_dia(self):
        return self.total_ingresos - self.total_egresos


class PresupuestoMensual(models.Model):
    """
    Presupuesto mensual por categoría. Permite comparar real vs presupuestado.
    """
    CATEGORIAS = [
        ('ventas', 'Ventas / Ingresos'),
        ('costo_venta', 'Costo de Ventas'),
        ('remuneraciones', 'Remuneraciones'),
        ('arriendo', 'Arriendo'),
        ('servicios_basicos', 'Servicios Básicos'),
        ('marketing', 'Marketing / Publicidad'),
        ('logistica', 'Logística / Transporte'),
        ('impuestos', 'Impuestos'),
        ('financiero', 'Gastos Financieros'),
        ('otros_gastos', 'Otros Gastos'),
    ]
    anio = models.IntegerField()
    mes = models.IntegerField()
    categoria = models.CharField(max_length=30, choices=CATEGORIAS)
    monto_presupuestado = models.DecimalField(max_digits=14, decimal_places=0)
    notas = models.TextField(blank=True)

    class Meta:
        unique_together = ['anio', 'mes', 'categoria']
        ordering = ['-anio', '-mes', 'categoria']

    def __str__(self):
        return f"{self.anio}/{self.mes:02d} - {self.get_categoria_display()}"


class ConfiguracionEmpresa(models.Model):
    """Configuración general de la empresa (singleton)"""
    nombre = models.CharField(max_length=200, default='Mi Empresa')
    rut = models.CharField(max_length=20, blank=True)
    giro = models.CharField(max_length=200, blank=True)
    direccion = models.TextField(blank=True)
    telefono = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    moneda = models.CharField(max_length=5, default='CLP')
    saldo_inicial_caja = models.DecimalField(max_digits=14, decimal_places=0, default=0)
    saldo_inicial_banco = models.DecimalField(max_digits=14, decimal_places=0, default=0)
    fecha_inicio_operaciones = models.DateField(null=True, blank=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Configuración'

    def __str__(self):
        return self.nombre

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj
