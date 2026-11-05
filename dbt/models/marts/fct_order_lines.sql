-- One row per order line. TPC-H line numbers run 1..7, so orderkey * 10 + linenumber is unique.
select
    l.l_orderkey * 10 + l.l_linenumber            as order_line_id,
    l.l_orderkey                                   as order_key,
    o.o_custkey                                    as customer_key,
    l.l_partkey                                    as part_key,
    l.l_suppkey                                    as supplier_key,
    o.o_orderdate                                  as order_date,
    l.l_shipdate                                   as ship_date,
    l.l_shipmode                                   as ship_mode,
    l.l_returnflag                                 as return_flag,
    l.l_linestatus                                 as line_status,
    o.o_orderpriority                              as order_priority,
    o.o_orderstatus                                as order_status,
    l.l_quantity                                   as quantity,
    l.l_extendedprice                              as extended_price,
    l.l_discount                                   as discount,
    l.l_tax                                        as tax,
    case when l.l_receiptdate > l.l_commitdate then 1 else 0 end as is_late
from {{ source('tpch', 'lineitem') }} l
join {{ source('tpch', 'orders') }} o
  on o.o_orderkey = l.l_orderkey
