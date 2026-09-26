-- ============================================================================
-- Payroll Customer Map — production data build
-- Cohort: payroll-Live restaurant locations within 15 mi of Toast HQ.
-- ============================================================================
WITH
-- ── Deduplicated Salesforce customer rows (many SF children per EC GUID) ──────
cust_dd AS (
    SELECT SALESFORCE_ACCOUNTID, EC_CUSTOMER_GUID, ACCOUNT_OWNER_NAME, ACCOUNT_OWNER_EMAIL
    FROM TOAST.ANALYTICS_CORE.CUSTOMER
    WHERE EC_CUSTOMER_GUID IS NOT NULL
),

-- ── Locations: payroll-Live restaurants with coordinates ─────────────────────
loc_raw AS (
    SELECT
        r.toastorders_restaurant_guid                       AS rguid,
        r.RESTAURANT_NAME, r.RESTAURANT_LOCATION_NAME,
        r.ADDRESS_LINE_1, r.CITY, r.ZIPCODE,
        TRY_TO_DOUBLE(r.LATITUDE)                           AS lat,
        TRY_TO_DOUBLE(r.LONGITUDE)                          AS lon,
        cd.SALESFORCE_ACCOUNTID, cd.EC_CUSTOMER_GUID,
        cd.ACCOUNT_OWNER_NAME, cd.ACCOUNT_OWNER_EMAIL,
        ec.EC_COMPANY_CODE, ec.FIRST_CHECK_DATE
    FROM TOAST.EC_CORE.EC_CUSTOMER ec
    JOIN cust_dd cd                                     ON ec.EC_CUSTOMER_GUID = cd.EC_CUSTOMER_GUID
    JOIN TOAST.ANALYTICS_CORE.TOASTORDERS_CUSTOMER_BRIDGE b
                                                        ON cd.SALESFORCE_ACCOUNTID = b.salesforce_accountid
    JOIN TOAST.ANALYTICS_CORE.TOASTORDERS_RESTAURANT r   ON b.toastorders_restaurant_guid = r.toastorders_restaurant_guid
    WHERE ec.PAYROLL_STATUS = 'Live'
      AND r.is_deleted = FALSE AND r.is_active = TRUE
      -- NB: no is_in_test_mode filter — some real payroll-Live Boston
      -- restaurants (e.g. hugosrestaurant) are flagged test mode upstream.
      AND TRY_TO_DOUBLE(r.LATITUDE) IS NOT NULL
    QUALIFY ROW_NUMBER() OVER (PARTITION BY r.toastorders_restaurant_guid
             ORDER BY (cd.ACCOUNT_OWNER_NAME IS NOT NULL) DESC, cd.SALESFORCE_ACCOUNTID) = 1
),

loc AS (
    SELECT *,
        ROUND(HAVERSINE(lat, lon, 42.4073, -71.1454) * 0.621371, 1) AS dist_home,
        ROUND(HAVERSINE(lat, lon, 42.3498, -71.0484) * 0.621371, 1) AS dist_office
    FROM loc_raw
),

cohort AS (
    SELECT * FROM loc WHERE dist_office <= 15
),

ec_ids AS (SELECT DISTINCT EC_CUSTOMER_GUID FROM cohort),

-- ── Active payroll location count per EC customer ────────────────────────────
loc_counts AS (
    SELECT ec.EC_CUSTOMER_GUID, COUNT(*) AS location_count
    FROM TOAST.EC_CORE.EC_CUSTOMER_LOCATION ecl
    JOIN TOAST.EC_CORE.EC_CUSTOMER ec ON ecl.EC_CUSTOMER_ID = ec.EC_CUSTOMER_ID
    JOIN ec_ids i                     ON ec.EC_CUSTOMER_GUID = i.EC_CUSTOMER_GUID
    WHERE ecl.PAYROLL_STATUS = 'Live'
    GROUP BY 1
),

-- ── Active employee count per EC customer ────────────────────────────────────
emp_active AS (
    SELECT e.CUSTOMER_UUID, COUNT_IF(e.EC_EMPLOYMENT_STATUS = 'Active') AS active_employees
    FROM TOAST.EC_CORE.EC_EMPLOYEE e
    JOIN ec_ids i ON e.CUSTOMER_UUID = i.EC_CUSTOMER_GUID
    GROUP BY 1
),

-- ── Latest payroll product NPS response per EC customer ──────────────────────
nps AS (
    SELECT n.EC_CUSTOMER_GUID, n.PRODUCT_NPS_SCORE AS score
    FROM TOAST.PRODUCT.PAYROLL_PRODUCT_NPS n
    JOIN ec_ids i ON n.EC_CUSTOMER_GUID = i.EC_CUSTOMER_GUID
    WHERE n.PRODUCT_NPS_SCORE IS NOT NULL
    QUALIFY ROW_NUMBER() OVER (PARTITION BY n.EC_CUSTOMER_GUID ORDER BY n.BROWSER_TIME DESC) = 1
),

-- ── Care tickets, last 12 months (per EC customer) ───────────────────────────
tickets AS (
    SELECT cd.EC_CUSTOMER_GUID, COUNT(*) AS ticket_count
    FROM TOAST.CS_CUSTOMER_CARE.EC_SUPPORT_TICKET t
    JOIN cust_dd cd ON t.SALESFORCE_ACCOUNTID = cd.SALESFORCE_ACCOUNTID
    JOIN ec_ids i   ON cd.EC_CUSTOMER_GUID = i.EC_CUSTOMER_GUID
    WHERE t.CREATED_DATETIME >= DATEADD('month', -12, CURRENT_TIMESTAMP())
    GROUP BY 1
),

-- ── Scheduling (Sling): dedupe the event log to latest state per org ─────────
-- SLING_CURRENT is a 7.8B-row event log clustered on YYYYMMDD. The newest
-- partition is a full snapshot of all ~28k orgs, so filter on the bare cluster
-- key first — scanning the whole table times out.
sched AS (
    SELECT DISTINCT restaurant_guid
    FROM (
        SELECT restaurant_guid, org_status,
               ROW_NUMBER() OVER (PARTITION BY sling_org_id ORDER BY timestamp DESC) AS rn
        FROM TOAST.SOURCE_EC.SLING_CURRENT
        WHERE YYYYMMDD = (SELECT MAX(YYYYMMDD) FROM TOAST.SOURCE_EC.SLING_CURRENT)
          AND restaurant_guid IS NOT NULL
    ) latest
    WHERE rn = 1 AND org_status = 'Subscribed'
),

-- ── Tips Manager active ───────────────────────────────────────────────────────
tips_active AS (
    SELECT DISTINCT t.CUSTOMER_UUID
    FROM TOAST.SOURCE_EC.TIPS_CURRENT t JOIN ec_ids i ON t.CUSTOMER_UUID = i.EC_CUSTOMER_GUID
),

-- ── Bounced payroll in the last 6 months ──────────────────────────────────────
-- Bounces: any transaction type, last 6 months. DELETED is boolean FALSE for
-- most rows and NULL only on older ones — COALESCE, don't test IS NULL.
bounce_6mo AS (
    SELECT DISTINCT b.CUSTOMER_UUID
    FROM TOAST.SOURCE_EC.BOUNCED_PAYPERIOD_CURRENT b JOIN ec_ids i ON b.CUSTOMER_UUID = i.EC_CUSTOMER_GUID
    WHERE DATEADD('millisecond', b.BOUNCE_DATE, '1970-01-01'::TIMESTAMP_NTZ)
              >= DATEADD('month', -6, CURRENT_DATE()::TIMESTAMP_NTZ)
      AND COALESCE(b.DELETED, FALSE) = FALSE
),

-- ── Last user to process (open) payroll ──────────────────────────────────────
open_last AS (
    SELECT o.CUSTOMER_UUID, o.USER_UUID
    FROM TOAST.SOURCE_EC.PAYROLL_EVENTS_OPEN_PAYROLL_CURRENT o
    JOIN ec_ids i ON o.CUSTOMER_UUID = i.EC_CUSTOMER_GUID
    WHERE o.ISSUCCESSFUL = TRUE
    QUALIFY ROW_NUMBER() OVER (PARTITION BY o.CUSTOMER_UUID ORDER BY o.TIMESTAMP DESC) = 1
),
-- Estratex carries the real email (its names are MD5-hashed, so unusable)
poster_email AS (
    SELECT ol.CUSTOMER_UUID, ol.USER_UUID, su.EMAIL AS es_email
    FROM open_last ol
    LEFT JOIN TOAST.SOURCE_ESTRATEX.ESTRATEX_ST_USER_CURRENT su
           ON ol.USER_UUID IS NOT NULL AND ol.USER_UUID = su.UUID
    QUALIFY ROW_NUMBER() OVER (PARTITION BY ol.CUSTOMER_UUID ORDER BY (su.EMAIL IS NOT NULL) DESC) = 1
),
tw_by_guid AS (
    SELECT GUID, FIRSTNAME, LASTNAME, EMAIL
    FROM TOAST.SOURCE_TOAST_ORDERS.USERS_CURRENT
    QUALIFY ROW_NUMBER() OVER (PARTITION BY GUID ORDER BY SHARDGUID) = 1
),
tw_by_email AS (
    SELECT LOWER(EMAIL) AS lemail, FIRSTNAME, LASTNAME
    FROM TOAST.SOURCE_TOAST_ORDERS.USERS_CURRENT
    WHERE EMAIL IS NOT NULL AND FIRSTNAME IS NOT NULL
    QUALIFY ROW_NUMBER() OVER (PARTITION BY LOWER(EMAIL) ORDER BY SHARDGUID) = 1
),
poster AS (
    SELECT
        pe.CUSTOMER_UUID,
        TRIM(COALESCE(g.FIRSTNAME, te.FIRSTNAME, '') || ' ' ||
             COALESCE(g.LASTNAME,  te.LASTNAME,  ''))   AS poster_name,
        COALESCE(pe.es_email, g.EMAIL)                  AS poster_email
    FROM poster_email pe
    LEFT JOIN tw_by_guid  g  ON pe.USER_UUID = g.GUID
    LEFT JOIN tw_by_email te ON LOWER(pe.es_email) = te.lemail
)

-- ── OUTPUT: one row per restaurant location ──────────────────────────────────
SELECT
    c.dist_home                                             AS dh,
    c.dist_office                                           AS "DO",
    c.lat, c.lon,
    c.RESTAURANT_NAME                                       AS rest_name,
    c.RESTAURANT_LOCATION_NAME                              AS rest_loc_name,
    c.ADDRESS_LINE_1                                        AS addr,
    c.CITY                                                  AS city,
    LEFT(c.ZIPCODE, 5)                                      AS zip,
    COALESCE(lc.location_count, 1)                          AS locs,
    n.score                                                 AS pnps,
    CASE WHEN n.score IS NULL THEN ''
         WHEN n.score >= 9 THEN 'Promoter'
         WHEN n.score >= 7 THEN 'Passive'
         ELSE 'Detractor' END                               AS nps,
    COALESCE(tk.ticket_count, 0)                            AS tickets,
    IFF(sc.restaurant_guid IS NOT NULL, 'Yes', 'No')        AS sched,
    IFF(ta.CUSTOMER_UUID IS NOT NULL, 'Yes', 'No')          AS tips,
    NULLIF(p.poster_name, '')                               AS poster_name,
    p.poster_email                                          AS poster_email,
    TO_CHAR(c.FIRST_CHECK_DATE, 'YYYY-MM-DD')               AS first_payroll,
    TO_CHAR(ecs.MOST_RECENT_CHECK_DATE, 'YYYY-MM-DD')       AS last_run,
    COALESCE(ea.active_employees, 0)                        AS active_employees,
    IFF(b6.CUSTOMER_UUID IS NOT NULL, 'Yes', 'No')          AS bounced_6mo,
    c.ACCOUNT_OWNER_NAME                                    AS rep,
    c.ACCOUNT_OWNER_EMAIL                                   AS rep_email,
    LOWER(c.EC_COMPANY_CODE)                                AS cc
FROM cohort c
JOIN TOAST.EC_CORE.EC_CUSTOMER ecs ON c.EC_CUSTOMER_GUID = ecs.EC_CUSTOMER_GUID
                                  AND ecs.PAYROLL_STATUS = 'Live'
LEFT JOIN loc_counts  lc  ON c.EC_CUSTOMER_GUID = lc.EC_CUSTOMER_GUID
LEFT JOIN emp_active  ea  ON c.EC_CUSTOMER_GUID = ea.CUSTOMER_UUID
LEFT JOIN nps         n   ON c.EC_CUSTOMER_GUID = n.EC_CUSTOMER_GUID
LEFT JOIN tickets     tk  ON c.EC_CUSTOMER_GUID = tk.EC_CUSTOMER_GUID
LEFT JOIN sched       sc  ON c.rguid = sc.restaurant_guid
LEFT JOIN poster      p   ON c.EC_CUSTOMER_GUID = p.CUSTOMER_UUID
LEFT JOIN tips_active ta  ON c.EC_CUSTOMER_GUID = ta.CUSTOMER_UUID
LEFT JOIN bounce_6mo  b6  ON c.EC_CUSTOMER_GUID = b6.CUSTOMER_UUID
QUALIFY ROW_NUMBER() OVER (PARTITION BY c.rguid ORDER BY ecs.MOST_RECENT_CHECK_DATE DESC NULLS LAST) = 1
ORDER BY c.dist_office
