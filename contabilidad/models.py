from django.db import models
from django.utils import timezone
import uuid


class CuentaContable(models.Model):
    TIPOS = [
        ('activo', 'Activo'), ('pasivo', 'Pasivo'), ('patrimonio', 'Patrimonio'),
        ('ingreso', 'Ingreso'), ('gasto', 'Gasto'), ('costo', 'Costo de Venta'),
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
    nombre = models.CharField(max_length=100)
    descripcion = models.TextField(blank=True)
    activo = models.BooleanField(default=True)

    def __str__(self):
        return self.nombre


class CuentaFinanciera(models.Model):
    TIPOS_CUENTA = [
        ('cuenta_corriente', 'Cuenta Corriente'),
        ('cuenta_vista', 'Cuenta Vista / RUT'),
        ('billetera_digital', 'Billetera Digital'),
        ('credito', 'Línea de Crédito'),
        ('caja', 'Caja (Efectivo)'),
        ('otra', 'Otra'),
    ]
    MONEDAS = [
        ('CLP', 'Peso Chileno (CLP)'),
        ('USD', 'Dólar Americano (USD)'),
        ('EUR', 'Euro (EUR)'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    nombre = models.CharField(max_length=100)
    institucion = models.CharField(max_length=100)
    tipo_cuenta = models.CharField(max_length=20, choices=TIPOS_CUENTA, default='cuenta_corriente')
    moneda = models.CharField(max_length=5, choices=MONEDAS, default='CLP')
    titular = models.CharField(max_length=150, blank=True)
    numero_parcial = models.CharField(max_length=20, blank=True)
    activa = models.BooleanField(default=True)
    saldo_inicial = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    fecha_saldo_inicial = models.DateField(null=True, blank=True)
    notas = models.TextField(blank=True)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['institucion', 'moneda', 'nombre']
        verbose_name = 'Cuenta Financiera'
        verbose_name_plural = 'Cuentas Financieras'

    def __str__(self):
        return f"{self.nombre} ({self.moneda})"


class RegistroImportacion(models.Model):
    ESTADOS = [
        ('completado', 'Completado'),
        ('con_errores', 'Completado con errores'),
        ('revertido', 'Revertido'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    cuenta_financiera = models.ForeignKey(
        CuentaFinanciera, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='importaciones'
    )
    nombre_archivo = models.CharField(max_length=255)
    banco_detectado = models.CharField(max_length=100, blank=True)
    fecha_importacion = models.DateTimeField(auto_now_add=True)
    total_filas_archivo = models.IntegerField(default=0)
    total_importados = models.IntegerField(default=0)
    total_duplicados = models.IntegerField(default=0)
    total_errores = models.IntegerField(default=0)
    estado = models.CharField(max_length=20, choices=ESTADOS, default='completado')
    hash_archivo = models.CharField(max_length=64, unique=True)
    advertencias = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ['-fecha_importacion']
        verbose_name = 'Importación'

    def __str__(self):
        return f"{self.nombre_archivo} ({self.fecha_importacion.strftime('%d/%m/%Y %H:%M')})"


class MovimientoDiario(models.Model):
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

    CATEGORIAS_NORM = [
        ('venta', 'Venta / Boleta / Factura'),
        ('aporte_socio', 'Aporte de Socio'),
        ('interes_ganado', 'Interés Ganado'),
        ('reembolso', 'Reembolso'),
        ('pago_proveedor', 'Pago a Proveedor'),
        ('pago_importacion', 'Pago Importación'),
        ('gasto_logistica', 'Gasto Logístico'),
        ('remuneracion_norm', 'Remuneración'),
        ('gasto_operacional', 'Gasto Operacional'),
        ('comision_bancaria', 'Comisión Bancaria'),
        ('pago_impuesto', 'Pago Impuesto'),
        ('pago_prestamo_norm', 'Pago Préstamo'),
        ('transferencia_interna', 'Transferencia Interna'),
        ('conversion_divisa', 'Conversión de Divisa'),
        ('sin_clasificar', 'Sin Clasificar'),
    ]

    CATEGORIAS_NEUTRAS = {'transferencia_interna', 'conversion_divisa'}

    MONEDAS = [('CLP', 'CLP'), ('USD', 'USD'), ('EUR', 'EUR')]

    # Campos originales
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    fecha = models.DateField(default=timezone.now)
    tipo = models.CharField(max_length=40, choices=TIPOS)
    descripcion = models.CharField(max_length=250)
    monto = models.DecimalField(max_digits=18, decimal_places=2)
    medio_pago = models.CharField(max_length=20, choices=MEDIOS_PAGO, default='efectivo')
    cuenta = models.ForeignKey(CuentaContable, on_delete=models.SET_NULL, null=True, blank=True)
    centro_costo = models.ForeignKey(CentroCosto, on_delete=models.SET_NULL, null=True, blank=True)
    cantidad_documentos = models.IntegerField(null=True, blank=True)
    rut_contraparte = models.CharField(max_length=20, blank=True)
    nombre_contraparte = models.CharField(max_length=150, blank=True)
    monto_neto = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    monto_iva = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    notas = models.TextField(blank=True)
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    # Campos NUEVOS (todos null=True para compatibilidad con registros existentes)
    cuenta_financiera = models.ForeignKey(
        CuentaFinanciera, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='movimientos'
    )
    moneda = models.CharField(max_length=5, choices=MONEDAS, default='CLP')
    monto_moneda_orig = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    tipo_cambio = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    tc_pendiente = models.BooleanField(default=False)  # True = TC no vino en cartola, requiere ingreso manual
    importacion = models.ForeignKey(
        RegistroImportacion, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='movimientos'
    )
    referencia_externa = models.CharField(max_length=100, blank=True)
    es_transferencia_interna = models.BooleanField(default=False)
    movimiento_relacionado = models.ForeignKey(
        'self', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='movimientos_relacionados'
    )
    categoria_normalizada = models.CharField(
        max_length=30, choices=CATEGORIAS_NORM,
        default='sin_clasificar', blank=True
    )
    tercero = models.CharField(max_length=200, blank=True)
    pais_tercero = models.CharField(max_length=5, blank=True)
    clasificacion_confianza = models.CharField(
        max_length=10, blank=True,
        choices=[('alta', 'Alta'), ('media', 'Media'), ('baja', 'Baja')]
    )
    clasificacion_razon = models.CharField(max_length=250, blank=True)

    class Meta:
        ordering = ['-fecha', '-creado_en']
        verbose_name = 'Movimiento Diario'
        indexes = [
            models.Index(fields=['fecha', 'cuenta_financiera']),
            models.Index(fields=['categoria_normalizada']),
            models.Index(fields=['es_transferencia_interna']),
        ]

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

    @property
    def afecta_resultado(self):
        return not self.es_transferencia_interna and \
               self.categoria_normalizada not in self.CATEGORIAS_NEUTRAS




class ControlSaldoReal(models.Model):
    fecha = models.DateField(default=timezone.now, unique=True)
    pendiente_efectivo_clp = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    notas = models.TextField(blank=True)
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-fecha', '-creado_en']
        verbose_name = 'Control de Saldo Real'
        verbose_name_plural = 'Controles de Saldos Reales'

    def __str__(self):
        return f"Control saldos {self.fecha}"


class ControlSaldoRealDetalle(models.Model):
    control = models.ForeignKey(ControlSaldoReal, on_delete=models.CASCADE, related_name='detalles')
    cuenta_financiera = models.ForeignKey(CuentaFinanciera, on_delete=models.CASCADE, related_name='controles_saldo_real')
    saldo_real = models.DecimalField(max_digits=18, decimal_places=4, default=0)

    class Meta:
        ordering = ['cuenta_financiera__institucion', 'cuenta_financiera__nombre']
        unique_together = [('control', 'cuenta_financiera')]
        verbose_name = 'Detalle Control Saldo Real'
        verbose_name_plural = 'Detalles Control Saldo Real'

    def __str__(self):
        return f"{self.control.fecha} · {self.cuenta_financiera} · {self.saldo_real}"


class CierreDiario(models.Model):
    fecha = models.DateField(unique=True)
    saldo_inicial_caja = models.DecimalField(max_digits=18, decimal_places=0, default=0)
    total_ingresos = models.DecimalField(max_digits=18, decimal_places=0, default=0)
    total_egresos = models.DecimalField(max_digits=18, decimal_places=0, default=0)
    saldo_final_caja = models.DecimalField(max_digits=18, decimal_places=0, default=0)
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
    CATEGORIAS = [
        ('ventas', 'Ventas / Ingresos'), ('costo_venta', 'Costo de Ventas'),
        ('remuneraciones', 'Remuneraciones'), ('arriendo', 'Arriendo'),
        ('servicios_basicos', 'Servicios Básicos'), ('marketing', 'Marketing / Publicidad'),
        ('logistica', 'Logística / Transporte'), ('impuestos', 'Impuestos'),
        ('financiero', 'Gastos Financieros'), ('otros_gastos', 'Otros Gastos'),
    ]
    anio = models.IntegerField()
    mes = models.IntegerField()
    categoria = models.CharField(max_length=30, choices=CATEGORIAS)
    monto_presupuestado = models.DecimalField(max_digits=18, decimal_places=0)
    notas = models.TextField(blank=True)

    class Meta:
        unique_together = ['anio', 'mes', 'categoria']
        ordering = ['-anio', '-mes', 'categoria']

    def __str__(self):
        return f"{self.anio}/{self.mes:02d} - {self.get_categoria_display()}"


class ConfiguracionEmpresa(models.Model):
    nombre = models.CharField(max_length=200, default='Mi Empresa')
    rut = models.CharField(max_length=20, blank=True)
    giro = models.CharField(max_length=200, blank=True)
    direccion = models.TextField(blank=True)
    telefono = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    moneda = models.CharField(max_length=5, default='CLP')
    saldo_inicial_caja = models.DecimalField(max_digits=18, decimal_places=0, default=0)
    saldo_inicial_banco = models.DecimalField(max_digits=18, decimal_places=0, default=0)
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