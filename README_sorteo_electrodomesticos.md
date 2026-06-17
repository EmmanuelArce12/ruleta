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
- `SORTEO_SQLSERVER_DRIVER`: driver ODBC de SQL Server. Default `ODBC Driver 18 for SQL Server`.
- `DEBO_CREDENTIALS_KEY`: clave usada para cifrar la contraseña DEBO antes de guardarla en PostgreSQL.
- `FACTURACION_SQL`: opcional. Si no se define, el modulo usa una consulta por defecto para DEBO.

## Configuracion DEBO por estacion

Cada estacion carga desde el admin del sorteo:

- IP o host DEBO
- base de datos, por defecto `DEBO`
- usuario
- clave cifrada en backend

La validacion corre contra SQL Server de esa estacion. Ya no depende de una unica `FACTURACION_DATABASE_URL` global.

La consulta debe devolver estas columnas o alias compatibles:

- `combustible` o `producto`
- `litros` o `cantidad_litros`
- `pago_app_ypf`

Consulta default incluida en el modulo:

```sql
SELECT
    fecha_hora_ticket,
    numero_factura,
    vendedor,
    combustible,
    litros,
    pago_app_ypf
FROM ...
WHERE fecha_hora_ticket >= ?
  AND fecha_hora_ticket < DATEADD(SECOND, 1, ?)
```

La query default:

- toma solo `playa` (`LUG = 1`)
- toma solo facturas (`TCO LIKE 'F%'`)
- excluye remitos (`TCO <> 'RE'`)
- limita a `Super`, `Infinia`, `Diesel 500`, `Infinia Diesel`
- busca por segundo exacto del ticket

Si encuentra mas de un ticket en el mismo segundo, devuelve ambiguedad para no aprobar mal.

## Flujo

1. El administrador entra al modulo con su usuario admin existente.
2. Configura litros minimos y genera/imprime el QR.
3. El cliente carga fecha, hora con segundos y sus datos personales.
4. El registro aparece en vivo como `PENDIENTE`.
5. El proceso automatico, o el boton `Forzar consulta`, valida contra facturacion.
6. `Iniciar conteo` archiva el listado activo en `sorteo_conteos` y limpia la vista sin borrar datos.
