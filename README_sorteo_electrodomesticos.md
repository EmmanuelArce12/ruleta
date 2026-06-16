# Sorteo Electrodomesticos

Modulo independiente de la app principal. No modifica `app.py`; corre como otro proceso Flask y usa las credenciales admin ya existentes en la tabla `estaciones`. Para publicarlo sin abrir el puerto 5055, usar un proxy desde `/sorteo/` hacia el servicio interno.

Tambien se puede publicar dentro del mismo Gunicorn de la ruleta usando `wsgi.py`, que monta:

- app principal: `/`
- sorteo electrodomesticos: `/sorteo`

## Ejecutar local

```powershell
pip install -r requirements.txt
python sorteo_electrodomesticos.py
```

Admin local directo: `http://localhost:5055/admin`

Admin publicado por proxy: `https://sorteo.grpecheverria.com/sorteo/admin`

## Ejecutar junto con la ruleta

```bash
gunicorn -b 0.0.0.0:5000 wsgi:application
```

Si Docker estaba usando `app:app`, cambiarlo por `wsgi:application`.

## Variables nuevas

- `SORTEO_SECRET_KEY`: clave de sesion del modulo.
- `SORTEO_PORT`: puerto, por defecto `5055`.
- `SORTEO_PUBLIC_BASE_URL`: URL publica base para que el QR apunte al dominio correcto.
- `SORTEO_BASE_PATH`: prefijo publico del modulo, por defecto `/sorteo`.
- `FACTURACION_DATABASE_URL`: conexion a la base de facturacion. Si no existe, usa `DATABASE_URL`.
- `FACTURACION_SQL`: consulta parametrizada para validar tickets.

La consulta debe devolver estas columnas o alias compatibles:

- `combustible` o `producto`
- `litros` o `cantidad_litros`
- `pago_app_ypf`

Ejemplo orientativo:

```sql
SELECT producto AS combustible,
       cantidad AS litros,
       pago_app_ypf
FROM facturas
WHERE estacion_id = %(estacion_id)s
  AND numero_factura = %(numero_factura)s
  AND fecha_hora_ticket = %(ticket_hora)s
LIMIT 1
```

## Flujo

1. El administrador entra al modulo con su usuario admin existente.
2. Configura litros minimos y genera/imprime el QR.
3. El cliente carga fecha, hora con segundos, factura y datos personales.
4. El registro aparece en vivo como `PENDIENTE`.
5. El proceso automatico, o el boton `Forzar consulta`, valida contra facturacion.
6. `Iniciar conteo` archiva el listado activo en `sorteo_conteos` y limpia la vista sin borrar datos.
