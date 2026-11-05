{{ config(materialized='table') }}
select cast(d as date) as date_day
from range(date '1990-01-01', date '2001-01-01', interval 1 day) t(d)
