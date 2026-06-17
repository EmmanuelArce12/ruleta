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
SELECT TOP (15)
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


def preview_sql(limit: int = 15) -> str:
    safe_limit = max(1, min(int(limit), 100))
    return DEFAULT_FACTURACION_SQL.replace("TOP (15)", f"TOP ({safe_limit})", 1)


def ticket_lookup_sql(include_remitos: bool = False) -> str:
    tco_condition = "1 = 1" if include_remitos else "f.TCO <> 'RE'"
    return f"""
WITH FacturaObjetivo AS (
    SELECT TOP (1)
        f.FEC AS fecha_hora_ticket,
        f.SUC,
        f.NCO,
        f.TCO,
        f.TIP,
        RTRIM(v.NomVen) AS vendedor,
        CAST(
            CASE
                WHEN EXISTS (
                    SELECT 1
                    FROM dbo.A_MERCADOPAGO_META_YPF p
                    WHERE p.FEC = f.FEC
                      AND RIGHT(LTRIM(RTRIM(p.fuel_station_id)), 3) = RIGHT('000' + CAST(f.SUC AS VARCHAR(10)), 3)
                      AND ABS(CAST(f.TOT AS DECIMAL(18,2)) - CAST(p.total_payment_amount AS DECIMAL(18,2))) < 0.05
                      AND p.payment_type = 'YPF_ACCOUNT_MONEY'
                ) THEN 1
                ELSE 0
            END
        AS bit) AS pago_app_ypf
    FROM dbo.AMAEFACT f
    LEFT JOIN dbo.VENDEDORES v
        ON f.OPE = v.CodVen
    WHERE f.ANU = ''
      AND f.LUG = 1
      AND f.FEC >= ?
      AND f.FEC < DATEADD(SECOND, 1, ?)
      AND f.SUC = ?
      AND f.NCO = ?
      AND {tco_condition}
    ORDER BY f.FEC DESC
),
Lineas AS (
    SELECT
        fo.fecha_hora_ticket,
        CAST(fo.SUC AS VARCHAR(10)) + '-' + CAST(fo.NCO AS VARCHAR(20)) AS numero_factura,
        fo.vendedor,
        fo.pago_app_ypf,
        fo.TCO AS tipo_comprobante,
        fo.TIP AS letra_fiscal,
        CASE
            WHEN d.SEC = 0 AND d.ART = 1 THEN 'Super'
            WHEN d.SEC = 0 AND d.ART = 2 THEN 'Infinia Diesel'
            WHEN d.SEC = 0 AND d.ART = 3 THEN 'Diesel 500'
            WHEN d.SEC = 0 AND d.ART = 4 THEN 'Infinia'
            ELSE NULL
        END AS combustible_linea,
        CASE
            WHEN d.SEC = 0 AND d.ART IN (1, 2, 3, 4) THEN CAST(d.CAN AS DECIMAL(18,4))
            ELSE CAST(0 AS DECIMAL(18,4))
        END AS litros_linea,
        CASE
            WHEN d.SEC = 0 AND d.ART IN (1, 2, 3, 4) THEN 1
            ELSE 0
        END AS es_promo,
        CASE
            WHEN d.SEC = 0 AND d.ART IN (2, 4) THEN 2
            WHEN d.SEC = 0 AND d.ART IN (1, 3) THEN 1
            ELSE 0
        END AS base_chances,
        CASE
            WHEN d.SEC = 0 AND d.ART IN (1, 2, 3, 4) THEN 0
            ELSE 1
        END AS es_no_valida
    FROM FacturaObjetivo fo
    INNER JOIN dbo.AMOVSTOC d
        ON fo.SUC = d.PVE
       AND fo.NCO = d.NCO
       AND fo.TIP = d.TIP
       AND fo.TCO = d.TCO
    WHERE d.LUG = 1
)
SELECT
    fecha_hora_ticket,
    numero_factura,
    vendedor,
    CASE
        WHEN SUM(es_promo) = 0 THEN NULL
        WHEN COUNT(DISTINCT CASE WHEN es_promo = 1 THEN combustible_linea END) = 1
            THEN MAX(CASE WHEN es_promo = 1 THEN combustible_linea END)
        ELSE 'Mixto'
    END AS combustible,
    CAST(SUM(litros_linea) AS DECIMAL(18,4)) AS litros,
    pago_app_ypf,
    tipo_comprobante,
    letra_fiscal,
    SUM(es_promo) AS promo_lineas,
    SUM(es_no_valida) AS lineas_no_validas,
    MAX(base_chances) AS base_chances
FROM Lineas
GROUP BY
    fecha_hora_ticket,
    numero_factura,
    vendedor,
    pago_app_ypf,
    tipo_comprobante,
    letra_fiscal
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


def validate_ticket_identity(
    station: dict,
    ticket_hora: datetime,
    sucursal: int,
    numero: int,
    include_remitos: bool = False,
):
    rows = run_query(
        station,
        ticket_lookup_sql(include_remitos=include_remitos),
        (ticket_hora, ticket_hora, int(sucursal), int(numero)),
    )
    if not rows:
        return None, "No se encontro una factura para esa fecha, hora exacta y numero."
    return rows[0], None
