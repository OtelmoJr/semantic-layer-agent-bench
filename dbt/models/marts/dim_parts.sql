select
    p.p_partkey    as part_key,
    p.p_brand      as brand,
    p.p_mfgr       as manufacturer,
    p.p_type       as part_type,
    p.p_size       as size,
    p.p_container  as container
from {{ source('tpch', 'part') }} p
