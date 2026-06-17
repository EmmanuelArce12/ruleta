from __future__ import annotations

from datetime import datetime
import os

try:
    import pyodbc
except ImportError:
    pyodbc = None

from secure_config import decrypt_secret


SQLSERVER_DRIVER = os.environ.get("SORTEO_SQLSERVER_DRIVER", "ODBC Driver 18 for SQL Server")

DEFAULT_FACTURACION_SQL = """
WITH TicketsDB AS (
    SELECT
        f.FEC AS fecha_hora_ticket,
        CAST(f.SUC AS VARCHAR(10)) + '-' + CAST(f.NCO AS VARCHAR(20)) AS numero_factura,
        RTRIM(v.NomVen) AS vendedor,
        CASE
            WHEN d.ART = 1 THEN 'Super'
            WHEN d.ART = 2 THEN 'Infinia Diesel'
            WHEN d.ART = 3 THEN 'Diesel 500'
            WHEN d.ART = 4 THEN 'Infinia'
            ELSE RTRIM(art.DetArt)
        END AS combustible,
        CAST(SUM(d.CAN) AS DECIMAL(18,4)) AS litros,
        CAST(0 AS bit) AS pago_app_ypf,
        f.TCO AS tipo_comprobante,
        f.TIP AS letra_fiscal
    FROM dbo.AMAEFACT f
    INNER JOIN dbo.AMOVSTOC d
        ON f.SUC = d.PVE
       AND f.NCO = d.NCO
       AND f.TIP = d.TIP
       AND f.TCO = d.TCO
    INNER JOIN dbo.ARTICULOS art
        ON d.SEC = art.CodSec
       AND d.ART = art.CodArt
    LEFT JOIN dbo.VENDEDORES v
        ON f.OPE = v.CodVen
    WHERE f.ANU = ''
      AND f.LUG = 1
      AND d.LUG = 1
      AND f.TCO LIKE 'F%'
      AND f.TCO <> 'RE'
      AND d.SEC = 0
      AND d.ART IN (1, 2, 3, 4)
      AND f.FEC >= ?
      AND f.FEC < DATEADD(SECOND, 1, ?)
    GROUP BY
        f.FEC,
        f.SUC,
        f.NCO,
        f.TCO,
        f.TIP,
        d.ART,
        art.DetArt,
        v.NomVen
)
SELECT
    fecha_hora_ticket,
    numero_factura,
    vendedor,
    combustible,
    litros,
    pago_app_ypf,
    tipo_comprobante,
    letra_fiscal
FROM TicketsDB
ORDER BY fecha_hora_ticket, numero_factura, combustible
"""


def preview_sql(limit: int = 15) -> str:
    safe_limit = max(1, min(int(limit), 100))
    return f"""
SELECT TOP ({safe_limit})
    f.FEC AS fecha_hora_ticket,
    CAST(f.SUC AS VARCHAR(10)) + '-' + CAST(f.NCO AS VARCHAR(20)) AS numero_factura,
    RTRIM(v.NomVen) AS vendedor,
    CASE
        WHEN d.ART = 1 THEN 'Super'
        WHEN d.ART = 2 THEN 'Infinia Diesel'
        WHEN d.ART = 3 THEN 'Diesel 500'
        WHEN d.ART = 4 THEN 'Infinia'
        ELSE RTRIM(art.DetArt)
    END AS combustible,
    CAST(SUM(d.CAN) AS DECIMAL(18,4)) AS litros,
    CAST(0 AS bit) AS pago_app_ypf,
    f.TCO AS tipo_comprobante,
    f.TIP AS letra_fiscal
FROM dbo.AMAEFACT f
INNER JOIN dbo.AMOVSTOC d
    ON f.SUC = d.PVE
   AND f.NCO = d.NCO
   AND f.TIP = d.TIP
   AND f.TCO = d.TCO
INNER JOIN dbo.ARTICULOS art
    ON d.SEC = art.CodSec
   AND d.ART = art.CodArt
LEFT JOIN dbo.VENDEDORES v
    ON f.OPE = v.CodVen
WHERE f.ANU = ''
  AND f.LUG = 1
  AND d.LUG = 1
  AND f.TCO LIKE 'F%'
  AND f.TCO <> 'RE'
  AND d.SEC = 0
  AND d.ART IN (1, 2, 3, 4)
GROUP BY
    f.FEC,
    f.SUC,
    f.NCO,
    f.TCO,
    f.TIP,
    d.ART,
    art.DetArt,
    v.NomVen
ORDER BY f.FEC DESC, numero_factura DESC, combustible
"""


def station_debo_ready(station: dict | None) -> bool:
    return bool(
        station
        and station.get("debo_host")
        and station.get("debo_user")
        and (station.get("debo_password_encrypted") or station.get("debo_password"))
    )


def station_with_decrypted_password(station: dict | None) -> dict | None:
    if not station:
        return station
    normalized = dict(station)
    encrypted = normalized.get("debo_password_encrypted")
    plaintext = normalized.get("debo_password")
    normalized["debo_password"] = decrypt_secret(encrypted) if encrypted else (plaintext or "")
    return normalized


def connect_station_sql_server(station: dict):
    if pyodbc is None:
        raise RuntimeError("Falta instalar pyodbc para consultar SQL Server.")
    if not station_debo_ready(station):
        raise RuntimeError("Falta configurar IP, base, usuario o clave de DEBO para esta estacion.")
    station = station_with_decrypted_password(station)

    connection_string = (
        f"DRIVER={{{SQLSERVER_DRIVER}}};"
        f"SERVER={station['debo_host']};"
        f"DATABASE={station.get('debo_database') or 'DEBO'};"
        f"UID={station['debo_user']};"
        f"PWD={station['debo_password']};"
        "Encrypt=no;"
        "TrustServerCertificate=yes;"
    )
    return pyodbc.connect(connection_string, timeout=15)


def run_query(station: dict, sql: str, params=()):
    conn = None
    try:
        conn = connect_station_sql_server(station)
        cur = conn.cursor()
        cur.execute(sql, *params)
        columns = [col[0] for col in cur.description]
        rows = [dict(zip(columns, row)) for row in cur.fetchall()]
        return rows
    finally:
        if conn is not None:
            conn.close()


def preview_station_tickets(station: dict, limit: int = 15):
    return run_query(station, preview_sql(limit))


def validate_ticket_second(station: dict, ticket_hora: datetime, sql: str | None = None):
    rows = run_query(station, sql or DEFAULT_FACTURACION_SQL, (ticket_hora, ticket_hora))
    if not rows:
        return None, "No se encontro un ticket de playa para ese segundo exacto."
    if len(rows) > 1:
        return None, f"Se encontraron {len(rows)} tickets en el mismo segundo. Hace falta un identificador adicional."
    return rows[0], None
