select
    s.s_suppkey  as supplier_key,
    s.s_name     as name,
    n.n_name     as nation,
    r.r_name     as region
from {{ source('tpch', 'supplier') }} s
join {{ source('tpch', 'nation') }} n on n.n_nationkey = s.s_nationkey
join {{ source('tpch', 'region') }} r on r.r_regionkey = n.n_regionkey
